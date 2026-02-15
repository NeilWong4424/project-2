"""Tools for managing club admins."""
import logging
from typing import Any, Dict, Optional

from google.cloud import firestore

from .validation import ValidationError, validate_club_ref, validate_email

logger = logging.getLogger(__name__)


def _club_ref_matches(stored_value: Any, expected_club_ref: str) -> bool:
    # Accept both string and DocumentReference-style values.
    # This lets us compare Firestore data that may store club_ref either as:
    # - a string path (e.g., "club/abc123"), or
    # - a DocumentReference (with a .path attribute).
    if isinstance(stored_value, str):
        return stored_value.strip() == expected_club_ref.strip()
    if hasattr(stored_value, "path"):  # DocumentReference
        return stored_value.path == expected_club_ref.strip()
    return str(stored_value) == expected_club_ref.strip()


async def _get_club_ref(db: firestore.AsyncClient, club_ref: str):
    if "/" in club_ref:
        return db.document(club_ref)
    return db.collection("club").document(club_ref)


async def invite_admin(club_ref: str, email: str) -> Dict[str, Any]:
    """Invite a user as club admin by email."""
    try:
        # 1) Validate inputs and fetch the club doc.
        #    - club_ref may be a full path ("club/xyz") or just an ID ("xyz").
        #    - email is normalized to lowercase to avoid duplicates.
        validate_club_ref(club_ref)
        email_norm = validate_email(email)["email"]

        db = firestore.AsyncClient()
        club_doc = await _get_club_ref(db, club_ref.strip())
        club_snap = await club_doc.get()
        if not club_snap.exists:
            return {"status": "error", "error": "Club not found"}

        # 2) Add email to the club's admin array (source of truth).
        #    Firestore ArrayUnion guarantees we don't add duplicates.
        await club_doc.update({"admin": firestore.ArrayUnion([email_norm])})

        # 3) If a user record exists, mark them as club_admin and link the club.
        #    We only update an existing user record; we do NOT create one here.
        #    If the user already belongs to a different club, block the invite.
        user_query = db.collection("users").where("email", "==", email_norm).limit(1)
        user_docs = await user_query.get()
        if user_docs:
            user_doc = user_docs[0]
            user_data = user_doc.to_dict() or {}
            stored_ref = user_data.get("club_ref")
            if stored_ref and not _club_ref_matches(stored_ref, club_ref):
                return {
                    "status": "error",
                    "error": "User belongs to a different club.",
                }
            await user_doc.reference.update(
                {"club_ref": club_ref.strip(), "club_admin": True}
            )

        return {"status": "success", "message": f"Admin invited: {email_norm}."}

    except ValidationError as e:
        logger.warning(f"Validation error inviting admin: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error inviting admin: {e}")
        return {"status": "error", "error": str(e)}


async def remove_admin(club_ref: str, email: str) -> Dict[str, Any]:
    """Remove a club admin by email."""
    try:
        # 1) Validate inputs and fetch the club doc.
        #    We only proceed if the club exists.
        validate_club_ref(club_ref)
        email_norm = validate_email(email)["email"]

        db = firestore.AsyncClient()
        club_doc = await _get_club_ref(db, club_ref.strip())
        club_snap = await club_doc.get()
        if not club_snap.exists:
            return {"status": "error", "error": "Club not found"}

        # 2) Remove from the club's admin array (source of truth).
        #    Firestore ArrayRemove is safe even if the email is not present.
        await club_doc.update({"admin": firestore.ArrayRemove([email_norm])})

        # 3) If a user record exists for this email + club, clear club_admin.
        #    We only clear the flag if the stored club_ref matches this club.
        user_query = db.collection("users").where("email", "==", email_norm).limit(1)
        user_docs = await user_query.get()
        if user_docs:
            user_doc = user_docs[0]
            user_data = user_doc.to_dict() or {}
            stored_ref = user_data.get("club_ref")
            if stored_ref and _club_ref_matches(stored_ref, club_ref):
                await user_doc.reference.update({"club_admin": False})

        return {"status": "success", "message": f"Admin removed: {email_norm}."}

    except ValidationError as e:
        logger.warning(f"Validation error removing admin: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        return {"status": "error", "error": str(e)}
