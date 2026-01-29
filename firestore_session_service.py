# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Firestore-based session service for ADK agents.

This module provides a Firestore implementation of the BaseSessionService,
enabling persistent session storage in Google Cloud Firestore.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime
from datetime import timezone
import logging
from typing import Any
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient
from google.adk.events.event import Event
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from google.adk.sessions.state import State
from google.adk.errors.already_exists_error import AlreadyExistsError

import uuid

logger = logging.getLogger("google_adk." + __name__)


def _extract_state_delta(
    state: Optional[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Extracts app, user, and session state deltas from a state dictionary."""
    deltas = {"app": {}, "user": {}, "session": {}}
    if state:
        for key in state.keys():
            if key.startswith(State.APP_PREFIX):
                deltas["app"][key.removeprefix(State.APP_PREFIX)] = state[key]
            elif key.startswith(State.USER_PREFIX):
                deltas["user"][key.removeprefix(State.USER_PREFIX)] = state[key]
            elif not key.startswith(State.TEMP_PREFIX):
                deltas["session"][key] = state[key]
    return deltas


def _merge_state(
    app_state: dict[str, Any],
    user_state: dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
    """Merge app, user, and session states into a single state dictionary."""
    merged_state = copy.deepcopy(session_state)
    for key in app_state.keys():
        merged_state[State.APP_PREFIX + key] = app_state[key]
    for key in user_state.keys():
        merged_state[State.USER_PREFIX + key] = user_state[key]
    return merged_state


class FirestoreSessionService(BaseSessionService):
    """A session service that uses Google Cloud Firestore for storage.

    This service stores sessions, events, and state in Firestore collections.

    Firestore Structure:
    - sessions/{app_name}/users/{user_id}/sessions/{session_id}
    - sessions/{app_name}/users/{user_id}/sessions/{session_id}/events/{event_id}
    - app_states/{app_name}
    - user_states/{app_name}/users/{user_id}
    """

    def __init__(
        self,
        project: Optional[str] = None,
        database: str = "(default)",
        collection_prefix: str = "adk",
    ):
        """Initializes the Firestore session service.

        Args:
            project: The Google Cloud project ID. If None, uses the default
                     project from the environment.
            database: The Firestore database ID to use.
            collection_prefix: Prefix for Firestore collections to avoid
                               conflicts with other data.
        """
        self._project = project
        self._database = database
        self._collection_prefix = collection_prefix
        self._client: Optional[AsyncClient] = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> AsyncClient:
        """Gets or creates the async Firestore client."""
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = AsyncClient(
                        project=self._project,
                        database=self._database,
                    )
        return self._client

    def _get_collection_name(self, name: str) -> str:
        """Gets the full collection name with prefix."""
        return f"{self._collection_prefix}_{name}"

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """Creates a new session in Firestore.

        Args:
            app_name: The name of the app.
            user_id: The id of the user.
            state: The initial state of the session.
            session_id: The client-provided id of the session. If not provided,
                        a generated ID will be used.

        Returns:
            The newly created session instance.

        Raises:
            AlreadyExistsError: If a session with the given session_id already exists.
        """
        client = await self._get_client()

        # Generate session ID if not provided
        if session_id is None:
            session_id = str(uuid.uuid4())

        # Check if session already exists
        sessions_collection = self._get_collection_name("sessions")
        session_ref = (
            client.collection(sessions_collection)
            .document(app_name)
            .collection("users")
            .document(user_id)
            .collection("sessions")
            .document(session_id)
        )

        existing_session = await session_ref.get()
        if existing_session.exists:
            raise AlreadyExistsError(
                f"Session with id {session_id} already exists."
            )

        # Get or create app state
        app_states_collection = self._get_collection_name("app_states")
        app_state_ref = client.collection(app_states_collection).document(app_name)
        app_state_doc = await app_state_ref.get()
        if app_state_doc.exists:
            app_state = app_state_doc.to_dict().get("state", {})
        else:
            app_state = {}
            await app_state_ref.set({"state": {}})

        # Get or create user state
        user_states_collection = self._get_collection_name("user_states")
        user_state_ref = (
            client.collection(user_states_collection)
            .document(app_name)
            .collection("users")
            .document(user_id)
        )
        user_state_doc = await user_state_ref.get()
        if user_state_doc.exists:
            user_state = user_state_doc.to_dict().get("state", {})
        else:
            user_state = {}
            await user_state_ref.set({"state": {}})

        # Extract state deltas from initial state
        state_deltas = _extract_state_delta(state)
        app_state_delta = state_deltas["app"]
        user_state_delta = state_deltas["user"]
        session_state = state_deltas["session"]

        # Apply state deltas
        if app_state_delta:
            app_state = {**app_state, **app_state_delta}
            await app_state_ref.update({"state": app_state})

        if user_state_delta:
            user_state = {**user_state, **user_state_delta}
            await user_state_ref.update({"state": user_state})

        # Create the session document
        now = datetime.now(timezone.utc)
        session_data = {
            "app_name": app_name,
            "user_id": user_id,
            "id": session_id,
            "state": session_state,
            "create_time": now,
            "update_time": now,
        }
        await session_ref.set(session_data)

        # Build and return the session object
        merged_state = _merge_state(app_state, user_state, session_state)
        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=merged_state,
            events=[],
            last_update_time=now.timestamp(),
        )

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        """Gets a session from Firestore.

        Args:
            app_name: The name of the app.
            user_id: The id of the user.
            session_id: The id of the session.
            config: Optional configuration for filtering events.

        Returns:
            The session if found, None otherwise.
        """
        client = await self._get_client()

        # Get the session document
        sessions_collection = self._get_collection_name("sessions")
        session_ref = (
            client.collection(sessions_collection)
            .document(app_name)
            .collection("users")
            .document(user_id)
            .collection("sessions")
            .document(session_id)
        )

        session_doc = await session_ref.get()
        if not session_doc.exists:
            return None

        session_data = session_doc.to_dict()

        # Get events for this session
        events_ref = session_ref.collection("events")
        query = events_ref.order_by("timestamp", direction=firestore.Query.DESCENDING)

        if config and config.after_timestamp:
            after_dt = datetime.fromtimestamp(config.after_timestamp, timezone.utc)
            query = query.where("timestamp", ">=", after_dt)

        if config and config.num_recent_events:
            query = query.limit(config.num_recent_events)

        events_docs = await query.get()
        events = []
        for event_doc in reversed(events_docs):
            event_data = event_doc.to_dict()
            events.append(self._doc_to_event(event_data))

        # Get app state
        app_states_collection = self._get_collection_name("app_states")
        app_state_ref = client.collection(app_states_collection).document(app_name)
        app_state_doc = await app_state_ref.get()
        app_state = app_state_doc.to_dict().get("state", {}) if app_state_doc.exists else {}

        # Get user state
        user_states_collection = self._get_collection_name("user_states")
        user_state_ref = (
            client.collection(user_states_collection)
            .document(app_name)
            .collection("users")
            .document(user_id)
        )
        user_state_doc = await user_state_ref.get()
        user_state = user_state_doc.to_dict().get("state", {}) if user_state_doc.exists else {}

        # Merge states
        session_state = session_data.get("state", {})
        merged_state = _merge_state(app_state, user_state, session_state)

        # Get update_time
        update_time = session_data.get("update_time")
        if isinstance(update_time, datetime):
            last_update_time = update_time.timestamp()
        else:
            last_update_time = 0.0

        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=merged_state,
            events=events,
            last_update_time=last_update_time,
        )

    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        """Lists all sessions for a user or all users.

        Args:
            app_name: The name of the app.
            user_id: The ID of the user. If not provided, lists all sessions
                     for all users.

        Returns:
            A ListSessionsResponse containing the sessions.
        """
        client = await self._get_client()

        sessions_collection = self._get_collection_name("sessions")

        # Get app state
        app_states_collection = self._get_collection_name("app_states")
        app_state_ref = client.collection(app_states_collection).document(app_name)
        app_state_doc = await app_state_ref.get()
        app_state = app_state_doc.to_dict().get("state", {}) if app_state_doc.exists else {}

        sessions = []

        if user_id is not None:
            # List sessions for a specific user
            sessions_ref = (
                client.collection(sessions_collection)
                .document(app_name)
                .collection("users")
                .document(user_id)
                .collection("sessions")
            )
            session_docs = await sessions_ref.get()

            # Get user state
            user_states_collection = self._get_collection_name("user_states")
            user_state_ref = (
                client.collection(user_states_collection)
                .document(app_name)
                .collection("users")
                .document(user_id)
            )
            user_state_doc = await user_state_ref.get()
            user_state = user_state_doc.to_dict().get("state", {}) if user_state_doc.exists else {}

            for session_doc in session_docs:
                session_data = session_doc.to_dict()
                session_state = session_data.get("state", {})
                merged_state = _merge_state(app_state, user_state, session_state)

                update_time = session_data.get("update_time")
                if isinstance(update_time, datetime):
                    last_update_time = update_time.timestamp()
                else:
                    last_update_time = 0.0

                sessions.append(
                    Session(
                        id=session_data.get("id", session_doc.id),
                        app_name=app_name,
                        user_id=user_id,
                        state=merged_state,
                        events=[],
                        last_update_time=last_update_time,
                    )
                )
        else:
            # List sessions for all users
            users_ref = (
                client.collection(sessions_collection)
                .document(app_name)
                .collection("users")
            )
            user_docs = await users_ref.get()

            # Get all user states
            user_states_collection = self._get_collection_name("user_states")
            user_states_ref = (
                client.collection(user_states_collection)
                .document(app_name)
                .collection("users")
            )
            user_state_docs = await user_states_ref.get()
            user_states_map = {}
            for user_state_doc in user_state_docs:
                user_states_map[user_state_doc.id] = user_state_doc.to_dict().get("state", {})

            for user_doc in user_docs:
                current_user_id = user_doc.id
                sessions_ref = user_doc.reference.collection("sessions")
                session_docs = await sessions_ref.get()

                user_state = user_states_map.get(current_user_id, {})

                for session_doc in session_docs:
                    session_data = session_doc.to_dict()
                    session_state = session_data.get("state", {})
                    merged_state = _merge_state(app_state, user_state, session_state)

                    update_time = session_data.get("update_time")
                    if isinstance(update_time, datetime):
                        last_update_time = update_time.timestamp()
                    else:
                        last_update_time = 0.0

                    sessions.append(
                        Session(
                            id=session_data.get("id", session_doc.id),
                            app_name=app_name,
                            user_id=current_user_id,
                            state=merged_state,
                            events=[],
                            last_update_time=last_update_time,
                        )
                    )

        return ListSessionsResponse(sessions=sessions)

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        """Deletes a session from Firestore.

        Args:
            app_name: The name of the app.
            user_id: The id of the user.
            session_id: The id of the session.
        """
        client = await self._get_client()

        sessions_collection = self._get_collection_name("sessions")
        session_ref = (
            client.collection(sessions_collection)
            .document(app_name)
            .collection("users")
            .document(user_id)
            .collection("sessions")
            .document(session_id)
        )

        # Delete all events in the session first
        events_ref = session_ref.collection("events")
        events_docs = await events_ref.get()
        for event_doc in events_docs:
            await event_doc.reference.delete()

        # Delete the session document
        await session_ref.delete()

    async def append_event(self, session: Session, event: Event) -> Event:
        """Appends an event to a session.

        Args:
            session: The session to append the event to.
            event: The event to append.

        Returns:
            The appended event.
        """
        if event.partial:
            return event

        # Trim temp state before persisting
        event = self._trim_temp_delta_state(event)

        client = await self._get_client()

        # Get the session document
        sessions_collection = self._get_collection_name("sessions")
        session_ref = (
            client.collection(sessions_collection)
            .document(session.app_name)
            .collection("users")
            .document(session.user_id)
            .collection("sessions")
            .document(session.id)
        )

        session_doc = await session_ref.get()
        if not session_doc.exists:
            raise ValueError(f"Session {session.id} not found")

        session_data = session_doc.to_dict()
        stored_update_time = session_data.get("update_time")
        if isinstance(stored_update_time, datetime):
            stored_timestamp = stored_update_time.timestamp()
        else:
            stored_timestamp = 0.0

        # Check if session has been updated since last loaded
        if stored_timestamp > session.last_update_time:
            # Reload the session state
            app_states_collection = self._get_collection_name("app_states")
            app_state_ref = client.collection(app_states_collection).document(session.app_name)
            app_state_doc = await app_state_ref.get()
            app_state = app_state_doc.to_dict().get("state", {}) if app_state_doc.exists else {}

            user_states_collection = self._get_collection_name("user_states")
            user_state_ref = (
                client.collection(user_states_collection)
                .document(session.app_name)
                .collection("users")
                .document(session.user_id)
            )
            user_state_doc = await user_state_ref.get()
            user_state = user_state_doc.to_dict().get("state", {}) if user_state_doc.exists else {}

            session_state = session_data.get("state", {})
            session.state = _merge_state(app_state, user_state, session_state)

            # Reload events
            events_ref = session_ref.collection("events")
            events_query = events_ref.order_by("timestamp", direction=firestore.Query.ASCENDING)
            events_docs = await events_query.get()
            session.events = [self._doc_to_event(e.to_dict()) for e in events_docs]

        # Extract state delta and update storage
        if event.actions and event.actions.state_delta:
            state_deltas = _extract_state_delta(event.actions.state_delta)
            app_state_delta = state_deltas["app"]
            user_state_delta = state_deltas["user"]
            session_state_delta = state_deltas["session"]

            # Update app state
            if app_state_delta:
                app_states_collection = self._get_collection_name("app_states")
                app_state_ref = client.collection(app_states_collection).document(session.app_name)
                app_state_doc = await app_state_ref.get()
                if app_state_doc.exists:
                    current_app_state = app_state_doc.to_dict().get("state", {})
                    updated_app_state = {**current_app_state, **app_state_delta}
                    await app_state_ref.update({"state": updated_app_state})
                else:
                    await app_state_ref.set({"state": app_state_delta})

            # Update user state
            if user_state_delta:
                user_states_collection = self._get_collection_name("user_states")
                user_state_ref = (
                    client.collection(user_states_collection)
                    .document(session.app_name)
                    .collection("users")
                    .document(session.user_id)
                )
                user_state_doc = await user_state_ref.get()
                if user_state_doc.exists:
                    current_user_state = user_state_doc.to_dict().get("state", {})
                    updated_user_state = {**current_user_state, **user_state_delta}
                    await user_state_ref.update({"state": updated_user_state})
                else:
                    await user_state_ref.set({"state": user_state_delta})

            # Update session state
            if session_state_delta:
                current_session_state = session_data.get("state", {})
                updated_session_state = {**current_session_state, **session_state_delta}
                await session_ref.update({"state": updated_session_state})

        # Update session update_time
        update_time = datetime.fromtimestamp(event.timestamp, timezone.utc)
        await session_ref.update({"update_time": update_time})

        # Store the event
        event_ref = session_ref.collection("events").document(event.id)
        event_data = self._event_to_doc(session, event)
        await event_ref.set(event_data)

        # Update session last_update_time
        session.last_update_time = update_time.timestamp()

        # Also update the in-memory session
        await super().append_event(session=session, event=event)
        return event

    def _event_to_doc(self, session: Session, event: Event) -> dict[str, Any]:
        """Converts an Event to a Firestore document dict."""
        return {
            "id": event.id,
            "app_name": session.app_name,
            "user_id": session.user_id,
            "session_id": session.id,
            "invocation_id": event.invocation_id,
            "author": event.author,
            "timestamp": datetime.fromtimestamp(event.timestamp, timezone.utc),
            "content": event.content.model_dump() if event.content else None,
            "actions": event.actions.model_dump() if event.actions else None,
            "branch": event.branch,
            "long_running_tool_ids": list(event.long_running_tool_ids) if event.long_running_tool_ids else None,
            "partial": event.partial,
            "turn_complete": event.turn_complete,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "interrupted": event.interrupted,
        }

    def _doc_to_event(self, doc: dict[str, Any]) -> Event:
        """Converts a Firestore document dict to an Event."""
        from google.genai import types

        # Handle content
        content = None
        if doc.get("content"):
            content = types.Content.model_validate(doc["content"])

        # Handle actions
        from google.adk.events.event_actions import EventActions
        actions = None
        if doc.get("actions"):
            actions = EventActions.model_validate(doc["actions"])

        # Handle timestamp
        timestamp = doc.get("timestamp")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.timestamp()
        elif timestamp is None:
            timestamp = datetime.now().timestamp()

        # Handle long_running_tool_ids
        long_running_tool_ids = None
        if doc.get("long_running_tool_ids"):
            long_running_tool_ids = set(doc["long_running_tool_ids"])

        return Event(
            id=doc.get("id", ""),
            invocation_id=doc.get("invocation_id", ""),
            author=doc.get("author", ""),
            content=content,
            actions=actions or EventActions(),
            timestamp=timestamp,
            branch=doc.get("branch"),
            long_running_tool_ids=long_running_tool_ids,
            partial=doc.get("partial", False),
            turn_complete=doc.get("turn_complete"),
            error_code=doc.get("error_code"),
            error_message=doc.get("error_message"),
            interrupted=doc.get("interrupted"),
        )

    async def close(self) -> None:
        """Closes the Firestore client."""
        if self._client:
            self._client.close()
            self._client = None

    async def __aenter__(self) -> "FirestoreSessionService":
        """Enters the async context manager and returns this service."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exits the async context manager and closes the service."""
        await self.close()
