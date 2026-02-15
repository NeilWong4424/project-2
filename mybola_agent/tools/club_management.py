"""Tools for managing club details."""
import logging
from typing import Any, Dict, Optional

from google.cloud import firestore

from .validation import ValidationError, validate_email, validate_phone, validate_text_field

logger = logging.getLogger(__name__)

async def register_club(
    name: str,
    phone_number: str,
    admin_email: Optional[str] = None,
    plan: str = "",
    reg: str = "",
    notice4: str = "",
    premium: bool = False,
) -> Dict[str, Any]:
    """Registers a new club.

    Args:
        name: Club name.
        phone_number: Primary contact phone number.
        admin_email: Optional admin email to seed the admin list.
        plan: Optional plan label (e.g., "Pelan Bisnes").
        reg: Optional registration number.
        notice4: Optional notice field.
        premium: Optional premium flag.
    """
    try:
        validate_text_field(name, "Name", min_length=2, max_length=100)
        validated_phone = validate_phone(phone_number)

        admin_list = []
        if admin_email:
            admin_list.append(validate_email(admin_email)["email"])

        data = {
            "name": name.strip(),
            "phone_number": validated_phone["phone"],
            "plan": plan.strip(),
            "reg": reg.strip(),
            "notice4": notice4.strip(),
            "premium": bool(premium),
            "admin": admin_list,
        }
        # Remove empty values to keep the document clean.
        data = {k: v for k, v in data.items() if v not in ("", [], None)}

        db = firestore.AsyncClient()
        ref = db.collection("club").document()
        await ref.set(data)

        return {"status": "success", "club_id": ref.id, "message": "Club registered."}

    except ValidationError as e:
        logger.warning(f"Validation error registering club: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error registering club: {e}")
        return {"status": "error", "error": str(e)}


async def update_club_details(club_ref: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates club information (e.g., name, address, contact)."""
    try:
        # 1) Resolve the club document reference from an ID or full path.
        #    Examples:
        #    - club_ref="club/abc123" -> db.document("club/abc123")
        #    - club_ref="abc123"      -> db.collection("club").document("abc123")
        db = firestore.AsyncClient()

        if "/" in club_ref:
            ref = db.document(club_ref)
        else:
            ref = db.collection("club").document(club_ref)

        # 2) Apply partial updates.
        #    Firestore update() only changes the provided fields and leaves
        #    all other fields untouched. It will fail if the document does not exist.
        await ref.update(updates)
        return {"status": "success", "message": "Club details updated."}

    except Exception as e:
        logger.error(f"Error updating club details: {e}")
        return {"status": "error", "error": str(e)}
