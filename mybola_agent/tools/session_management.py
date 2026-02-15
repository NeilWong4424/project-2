"""Tools for managing training sessions."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from google.cloud import firestore

from ..constants import COLLECTION_SESSIONS
from .firestore_read import read_club_data
from .validation import validate_date, validate_text_field

logger = logging.getLogger(__name__)


def _parse_session_datetime(date_value: Any, time_value: Optional[str]) -> datetime:
    if isinstance(date_value, datetime):
        return date_value
    if not isinstance(date_value, str):
        raise ValueError("date must be a string or datetime")
    date_str = date_value.strip()
    time_str = (time_value or "").strip()
    if time_str:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return validate_date(date_str)["parsed"]


async def create_training_session(
    club_ref: str,
    name: str,
    date: str,
    time: str = "",
    location: str = "",
    duration: int = 60,
    price: float = 0,
    age_group: str = "All age groups",
) -> Dict[str, Any]:
    """Creates a new training session for the club.

    Args:
        club_ref: The Firestore document path for the club.
        name: Session name (e.g., "Pagi").
        date: Date string (YYYY-MM-DD) or ISO datetime.
        time: Optional time string (HH:MM).
        location: Venue name.
        duration: Session duration in minutes.
        price: Session price.
        age_group: Age group label (e.g., "U13", "All age groups").

    Returns:
        Dict with status and session ID.
    """
    try:
        db = firestore.AsyncClient()

        validate_text_field(name, "Name", min_length=1, max_length=100)
        session_date = _parse_session_datetime(date, time)

        data = {
            "clubRef": club_ref,
            "name": name.strip(),
            "date": session_date,
            "duration": int(duration),
            "location": location,
            "price": float(price),
            "ageGroup": age_group,
            "createdAt": datetime.now(),
        }

        ref = db.collection(COLLECTION_SESSIONS).document()
        await ref.set(data)

        return {
            "status": "success",
            "session_id": ref.id,
            "message": f"Session '{name}' created successfully.",
        }

    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return {"status": "error", "error": str(e)}


async def update_training_session(
    club_ref: str, session_id: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Updates an existing training session.

    Args:
        club_ref: Reference to the club (for ownership verification)
        session_id: ID of the session to update
        updates: Dict of field:value pairs to update
    """
    try:
        # Verify session exists and belongs to this club
        check = await read_club_data(
            club_ref=club_ref, collection="sesi", doc_id=session_id
        )
        if check["status"] == "error":
            return {"status": "error", "error": "Session not found"}

        # Prevent changing club reference
        updates.pop("club_ref", None)
        updates.pop("clubRef", None)

        # Legacy field mapping
        if "title" in updates and "name" not in updates:
            updates["name"] = updates.pop("title")
        if "created_at" in updates and "createdAt" not in updates:
            updates["createdAt"] = updates.pop("created_at")
        if "age_group" in updates and "ageGroup" not in updates:
            updates["ageGroup"] = updates.pop("age_group")
        if "date" in updates and isinstance(updates["date"], str):
            updates["date"] = _parse_session_datetime(updates["date"], updates.get("time"))
        if "time" in updates:
            updates.pop("time", None)

        db = firestore.AsyncClient()
        ref = db.collection(COLLECTION_SESSIONS).document(session_id)
        await ref.update(updates)
        return {"status": "success", "message": "Session updated."}

    except Exception as e:
        logger.error(f"Error updating session: {e}")
        return {"status": "error", "error": str(e)}


async def delete_training_session(club_ref: str, session_id: str) -> Dict[str, Any]:
    """Deletes a training session.

    Args:
        club_ref: Reference to the club (for ownership verification)
        session_id: ID of the session to delete
    """
    try:
        # Verify session exists and belongs to this club
        check = await read_club_data(
            club_ref=club_ref, collection="sesi", doc_id=session_id
        )
        if check["status"] == "error":
            return {"status": "error", "error": "Session not found"}

        db = firestore.AsyncClient()
        await db.collection(COLLECTION_SESSIONS).document(session_id).delete()
        return {"status": "success", "message": "Session deleted."}

    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return {"status": "error", "error": str(e)}
