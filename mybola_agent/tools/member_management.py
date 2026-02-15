"""Tools for managing club members."""
import logging
from typing import Any, Dict, Optional

from google.cloud import firestore

from .firestore_read import read_club_data
from .validation import (
    ValidationError,
    validate_club_ref,
    validate_date,
    validate_phone,
    validate_text_field,
)

logger = logging.getLogger(__name__)


async def register_member(
    club_ref: str,
    name: str,
    telephone: Optional[str] = None,
    dob: Optional[str] = None,
    nota: Optional[str] = None,
    tag: Optional[list[str]] = None,
    # Legacy inputs (deprecated, kept for backward compatibility)
    ic_number: Optional[str] = None,
    phone: Optional[str] = None,
    parent_name: Optional[str] = None,
    parent_phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Registers a new member to the club.

    Args:
        club_ref: Reference to the club
        name: Member's full name (2-100 chars)
        telephone: Member's phone number (stored as "telephone")
        dob: Date of birth in YYYY-MM-DD (stored as Firestore timestamp)
        nota: Internal note/identifier (stored as "nota")
        tag: Optional list of tags (e.g., ["boy", "U13"])

        Legacy (deprecated):
        ic_number: If provided, mapped to "nota"
        phone: If provided, mapped to "telephone"

    Returns:
        Dict with status, member_id, and message
    """
    try:
        # Validate inputs
        validate_club_ref(club_ref)
        validate_text_field(name, "Name", min_length=2, max_length=100)
        telephone_value = (telephone or phone or "").strip()
        if not telephone_value:
            raise ValidationError("Telephone is required")
        validated_phone = validate_phone(telephone_value)

        nota_value = (nota or ic_number or "").strip()
        if nota_value:
            validate_text_field(nota_value, "Nota", min_length=1, max_length=100)

            # Check if member already exists (by nota)
            existing = await read_club_data(
                club_ref=club_ref,
                collection="member",
                filters=[{"field": "nota", "op": "==", "value": nota_value}],
                limit=1,
            )
            if existing["status"] == "success" and existing["count"] > 0:
                return {"status": "error", "error": "Member with this nota already exists."}

        parsed_dob = None
        if dob:
            parsed_dob = validate_date(dob)["parsed"]

        tag_list: list[str] = []
        if isinstance(tag, str):
            tag_list = [t.strip() for t in tag.split(",") if t.strip()]
        elif isinstance(tag, list):
            tag_list = [str(t).strip() for t in tag if str(t).strip()]

        db = firestore.AsyncClient()
        data = {
            "club_ref": club_ref.strip(),
            "name": name.strip(),
            "telephone": validated_phone["phone"],
            "dob": parsed_dob,
            "nota": nota_value or None,
            "tag": tag_list,
        }
        # Remove None values to keep documents clean
        data = {k: v for k, v in data.items() if v is not None}

        ref = db.collection("member").document()
        await ref.set(data)

        return {
            "status": "success",
            "member_id": ref.id,
            "message": f"Member {name} registered successfully.",
        }

    except ValidationError as e:
        logger.warning(f"Validation error registering member: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error registering member: {e}")
        return {"status": "error", "error": str(e)}


async def update_member(
    club_ref: str, member_id: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Updates member details.

    Args:
        club_ref: Reference to the club (for ownership verification)
        member_id: ID of the member to update
        updates: Dict of field:value pairs to update
    """
    try:
        # Verify document exists and belongs to this club
        check = await read_club_data(
            club_ref=club_ref, collection="member", doc_id=member_id
        )
        if check["status"] == "error":
            return {"status": "error", "error": "Member not found"}

        # Prevent changing club reference fields
        updates.pop("club_ref", None)
        updates.pop("clubRef", None)

        # Legacy field mapping
        if "phone" in updates and "telephone" not in updates:
            updates["telephone"] = updates.pop("phone")
        if "ic_number" in updates and "nota" not in updates:
            updates["nota"] = updates.pop("ic_number")
        if "tag" in updates and isinstance(updates["tag"], str):
            updates["tag"] = [t.strip() for t in updates["tag"].split(",") if t.strip()]
        if "dob" in updates and isinstance(updates["dob"], str):
            updates["dob"] = validate_date(updates["dob"])["parsed"]

        db = firestore.AsyncClient()
        ref = db.collection("member").document(member_id)
        await ref.update(updates)
        return {"status": "success", "message": "Member updated."}

    except Exception as e:
        logger.error(f"Error updating member: {e}")
        return {"status": "error", "error": str(e)}


async def delete_member(club_ref: str, member_id: str) -> Dict[str, Any]:
    """Deletes a member document.

    Args:
        club_ref: Reference to the club (for ownership verification)
        member_id: ID of the member to delete
    """
    try:
        # Verify document exists and belongs to this club
        check = await read_club_data(
            club_ref=club_ref, collection="member", doc_id=member_id
        )
        if check["status"] == "error":
            return {"status": "error", "error": "Member not found"}

        db = firestore.AsyncClient()
        ref = db.collection("member").document(member_id)
        await ref.delete()
        return {"status": "success", "message": "Member deleted."}

    except Exception as e:
        logger.error(f"Error deleting member: {e}")
        return {"status": "error", "error": str(e)}
