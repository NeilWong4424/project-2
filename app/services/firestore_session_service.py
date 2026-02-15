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

How it works:
  - Each "session" represents one conversation thread between a user and the agent.
  - Each "event" is a single turn within that conversation (a user message,
    an agent response, a tool call result, etc.).
  - "State" is a key-value dict that persists across turns within a session
    (e.g., user preferences, accumulated context). Only non-temporary keys
    are saved to Firestore; keys prefixed with "temp:" are ephemeral.

Firestore document layout:
  adk_sessions/{app_name}/users/{user_id}/sessions/{session_id}
      ├── fields: app_name, user_id, id, state, create_time, update_time
      └── sub-collection: events/{event_id}
            └── fields: id, author, content, actions, timestamp, ...

Typical flow:
  1. Telegram handler receives a message from a user.
  2. create_session() or get_session() fetches/creates the session.
  3. The ADK runner processes the message, producing events.
  4. append_event() stores each event and updates the session state.
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
    """Extracts session state deltas from a state dictionary.

    Filters out temporary keys (prefixed with "temp:") so they are never
    written to Firestore.  Temporary state is only needed within a single
    request and should not persist across turns.

    Args:
        state: The raw state dict that may contain both persistent and
               temporary keys.

    Returns:
        A dict like {"session": {<only persistent keys>}}.
    """
    deltas = {"session": {}}
    if state:
        for key in state.keys():
            # Skip ephemeral keys — they exist only for the current turn
            if not key.startswith(State.TEMP_PREFIX):
                deltas["session"][key] = state[key]
    return deltas


def _merge_state(session_state: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of the session state.

    A deep copy is used so that callers can freely mutate the returned dict
    without accidentally modifying the stored/cached version.
    """
    return copy.deepcopy(session_state)


class FirestoreSessionService(BaseSessionService):
    """A session service that uses Google Cloud Firestore for storage.

    This service stores sessions, events, and state in Firestore collections.

    Firestore Structure:
    - sessions/{app_name}/users/{user_id}/sessions/{session_id}
    - sessions/{app_name}/users/{user_id}/sessions/{session_id}/events/{event_id}
    """

    def __init__(
        self,
        project: Optional[str] = None,
        database: str = "(default)",
        collection_prefix: str = "adk",
    ):
        """Initializes the Firestore session service.

        The Firestore client is created lazily on the first request (not here)
        to avoid blocking the event loop at import time and to let the
        environment variables (GOOGLE_CLOUD_PROJECT, etc.) settle first.

        Args:
            project: The Google Cloud project ID. If None, uses the default
                     project from the environment (GOOGLE_CLOUD_PROJECT).
            database: The Firestore database ID to use. "(default)" is the
                      standard Firestore database in every GCP project.
            collection_prefix: Prefix for Firestore collections to avoid
                               naming conflicts with other data in the same
                               database.  Collections will be named like
                               "adk_sessions".
        """
        self._project = project
        self._database = database
        self._collection_prefix = collection_prefix
        # Client is created lazily via _get_client() — see below.
        self._client: Optional[AsyncClient] = None
        # Lock ensures only one coroutine creates the client (avoids race conditions).
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> AsyncClient:
        """Gets or creates the async Firestore client.

        Uses the double-checked locking pattern:
          1. First check without the lock (fast path — client already exists).
          2. Acquire the lock, then check again (slow path — only the first
             caller actually creates the client; others wait and then reuse it).
        """
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

        # Step 1: Generate a unique session ID if the caller didn't supply one.
        if session_id is None:
            session_id = str(uuid.uuid4())

        # Step 2: Build the Firestore document reference.
        # Path: adk_sessions / {app_name} / users / {user_id} / sessions / {session_id}
        sessions_collection = self._get_collection_name("sessions")
        session_ref = (
            client.collection(sessions_collection)
            .document(app_name)
            .collection("users")
            .document(user_id)
            .collection("sessions")
            .document(session_id)
        )

        # Step 3: Guard against duplicate session IDs.
        existing_session = await session_ref.get()
        if existing_session.exists:
            raise AlreadyExistsError(
                f"Session with id {session_id} already exists."
            )

        # Step 4: Strip temporary keys from the initial state before persisting.
        state_deltas = _extract_state_delta(state)
        session_state = state_deltas["session"]

        # Step 5: Write the session document to Firestore.
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

        # Step 6: Return an in-memory Session object with a deep-copied state
        # so the caller can mutate it without affecting the stored data.
        merged_state = _merge_state(session_state)
        return Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=merged_state,
            events=[],  # New session has no events yet
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

        # Step 1: Fetch the session document from Firestore.
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
            return None  # Session not found — caller should create one

        session_data = session_doc.to_dict()

        # Step 2: Query events from the "events" sub-collection.
        # Events are fetched in DESCENDING order so that .limit() gives us the
        # most *recent* N events.  We reverse them afterwards to restore
        # chronological order for the caller.
        events_ref = session_ref.collection("events")
        query = events_ref.order_by("timestamp", direction=firestore.Query.DESCENDING)

        # Optional: only fetch events after a certain timestamp (pagination).
        if config and config.after_timestamp:
            after_dt = datetime.fromtimestamp(config.after_timestamp, timezone.utc)
            query = query.where("timestamp", ">=", after_dt)

        # Optional: limit to the N most recent events (reduces payload size).
        if config and config.num_recent_events:
            query = query.limit(config.num_recent_events)

        events_docs = await query.get()
        events = []
        # reversed() restores chronological (oldest-first) order.
        for event_doc in reversed(events_docs):
            event_data = event_doc.to_dict()
            events.append(self._doc_to_event(event_data))

        # Step 3: Build the in-memory Session object.
        session_state = session_data.get("state", {})
        merged_state = _merge_state(session_state)

        # Convert Firestore datetime → UNIX timestamp (float).
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

            for session_doc in session_docs:
                session_data = session_doc.to_dict()
                session_state = session_data.get("state", {})
                merged_state = _merge_state(session_state)

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

            for user_doc in user_docs:
                current_user_id = user_doc.id
                sessions_ref = user_doc.reference.collection("sessions")
                session_docs = await sessions_ref.get()

                for session_doc in session_docs:
                    session_data = session_doc.to_dict()
                    session_state = session_data.get("state", {})
                    merged_state = _merge_state(session_state)

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

        # Firestore does NOT automatically delete sub-collections when you
        # delete a parent document, so we must delete each event doc first.
        events_ref = session_ref.collection("events")
        events_docs = await events_ref.get()
        for event_doc in events_docs:
            await event_doc.reference.delete()

        # Now safe to delete the session document itself.
        await session_ref.delete()

    async def append_event(self, session: Session, event: Event) -> Event:
        """Appends an event to a session.

        Args:
            session: The session to append the event to.
            event: The event to append.

        Returns:
            The appended event.
        """
        # Partial events are streaming chunks — don't persist them yet.
        if event.partial:
            return event

        # Remove temporary state keys (prefixed "temp:") from the event's
        # state delta so they never reach Firestore.
        event = self._trim_temp_delta_state(event)

        client = await self._get_client()

        # Step 1: Locate the session document in Firestore.
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

        # Step 2: Optimistic concurrency check.
        # If Firestore's update_time is newer than what we have in memory,
        # another request has modified this session concurrently.
        # We reload the authoritative state and events from Firestore to avoid
        # overwriting those changes.
        if stored_timestamp > session.last_update_time:
            session_state = session_data.get("state", {})
            session.state = _merge_state(session_state)

            events_ref = session_ref.collection("events")
            events_query = events_ref.order_by("timestamp", direction=firestore.Query.ASCENDING)
            events_docs = await events_query.get()
            session.events = [self._doc_to_event(e.to_dict()) for e in events_docs]

        # Step 3: Merge the event's state delta into the stored session state.
        # This is an incremental update — only changed keys are overwritten,
        # existing keys that weren't changed are preserved.
        if event.actions and event.actions.state_delta:
            state_deltas = _extract_state_delta(event.actions.state_delta)
            session_state_delta = state_deltas["session"]

            if session_state_delta:
                current_session_state = session_data.get("state", {})
                updated_session_state = {**current_session_state, **session_state_delta}
                await session_ref.update({"state": updated_session_state})

        # Step 4: Bump the session's update_time to the event's timestamp.
        update_time = datetime.fromtimestamp(event.timestamp, timezone.utc)
        await session_ref.update({"update_time": update_time})

        # Step 5: Persist the event itself in the events sub-collection.
        event_ref = session_ref.collection("events").document(event.id)
        event_data = self._event_to_doc(session, event)
        await event_ref.set(event_data)

        # Step 6: Sync in-memory session so subsequent code in this request
        # sees the latest timestamp and events list.
        session.last_update_time = update_time.timestamp()
        await super().append_event(session=session, event=event)
        return event

    def _event_to_doc(self, session: Session, event: Event) -> dict[str, Any]:
        """Converts an Event to a Firestore document dict.

        Pydantic models (content, actions) are serialized via .model_dump()
        so that Firestore stores plain dicts/lists rather than Python objects.
        """
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
        """Converts a Firestore document dict back to an Event object.

        This is the inverse of _event_to_doc().  Pydantic models are
        reconstructed via .model_validate(), and Firestore datetime objects
        are converted back to UNIX timestamps (floats).
        """
        from google.genai import types  # Lazy import to avoid circular deps

        # Reconstruct the Content pydantic model (user/agent message payload).
        content = None
        if doc.get("content"):
            content = types.Content.model_validate(doc["content"])

        # Reconstruct EventActions (state deltas, tool calls, auth requests, etc.).
        from google.adk.events.event_actions import EventActions
        actions = None
        if doc.get("actions"):
            actions = EventActions.model_validate(doc["actions"])

        # Firestore stores timestamps as datetime objects; convert to float.
        timestamp = doc.get("timestamp")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.timestamp()
        elif timestamp is None:
            timestamp = datetime.now().timestamp()

        # long_running_tool_ids is stored as a list in Firestore but the
        # Event model expects a set.
        long_running_tool_ids = None
        if doc.get("long_running_tool_ids"):
            long_running_tool_ids = set(doc["long_running_tool_ids"])

        return Event(
            id=doc.get("id", ""),
            invocation_id=doc.get("invocation_id", ""),
            author=doc.get("author", ""),          # "user" or agent name
            content=content,                        # The message payload
            actions=actions or EventActions(),       # State changes & tool calls
            timestamp=timestamp,                    # When this event occurred
            branch=doc.get("branch"),               # For multi-branch conversations
            long_running_tool_ids=long_running_tool_ids,
            partial=doc.get("partial", False),      # True for streaming chunks
            turn_complete=doc.get("turn_complete"), # Signals end of agent turn
            error_code=doc.get("error_code"),       # Non-None if an error occurred
            error_message=doc.get("error_message"),
            interrupted=doc.get("interrupted"),      # True if user interrupted
        )

    async def close(self) -> None:
        """Closes the Firestore client and releases its network resources.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._client:
            self._client.close()
            self._client = None

    # --- Async context manager support ---
    # Usage:  async with FirestoreSessionService() as svc: ...
    # This ensures the Firestore client is properly closed even if an
    # exception occurs.

    async def __aenter__(self) -> "FirestoreSessionService":
        """Enters the async context manager and returns this service."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exits the async context manager and closes the service."""
        await self.close()
