"""Tools for managing billing and payments."""
import logging
import random
from datetime import datetime
from typing import Any, Dict, Optional

from google.cloud import firestore

from ..constants import (
    ALLOWED_BILL_STATUSES,
    COLLECTION_BILLING,
    MAX_BATCH_SIZE,
)
from .firestore_read import read_club_data
from .validation import (
    ValidationError,
    validate_amount,
    validate_club_ref,
    validate_date,
    validate_member_id,
    validate_status,
    validate_text_field,
)

logger = logging.getLogger(__name__)


def _generate_invoice(dt: datetime) -> str:
    return f"{dt.strftime('%y%m%d')}-{random.randint(0, 9999):04d}"


def _parse_bill_date(date_value: Optional[str], due_date: Optional[str]) -> datetime:
    if date_value:
        try:
            return datetime.fromisoformat(date_value.strip())
        except ValueError:
            return validate_date(date_value)["parsed"]
    if due_date:
        return validate_date(due_date)["parsed"]
    return datetime.now()


async def issue_bill(
    club_ref: str,
    member_id: str,
    amount: float,
    description: str = "",
    due_date: Optional[str] = None,
    member_name: Optional[str] = None,
    member_ref: Optional[str] = None,
    user_ref: Optional[str] = None,
    premium: Optional[bool] = None,
    invoice: Optional[str] = None,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Issues a new bill to a member.

    Args:
        club_ref: Reference to the club
        member_id: ID of the member to bill
        amount: Bill amount in RM (must be > 0)
        description: Bill description (optional)
        due_date: Optional due date in YYYY-MM-DD format (mapped to "date")
        member_name: Optional member name (stored as "member")
        member_ref: Optional member document path (stored as "member_ref")
        user_ref: Optional user document path (stored as "user_ref")
        premium: Optional premium flag
        invoice: Optional invoice code
        date: Optional ISO date-time (overrides due_date)

    Returns:
        Dict with status, bill_id, and message
    """
    try:
        # Validate inputs
        validate_club_ref(club_ref)
        validate_member_id(member_id)
        validated_amount = validate_amount(amount, min_value=0.01)
        validate_text_field(description or "", "Description", min_length=0, max_length=500, allow_empty=True)

        db = firestore.AsyncClient()

        # Try to resolve member name if not provided
        resolved_member_name = (member_name or "").strip()
        if not resolved_member_name:
            member_lookup = await read_club_data(
                club_ref=club_ref,
                collection="member",
                doc_id=member_id.strip(),
                fields=["name"],
            )
            if member_lookup.get("status") == "success" and member_lookup.get("data"):
                resolved_member_name = member_lookup["data"][0].get("name", "")

        bill_date = _parse_bill_date(date, due_date)
        invoice_value = (invoice or "").strip() or _generate_invoice(bill_date)
        member_ref_value = (member_ref or "").strip() or f"member/{member_id.strip()}"

        data = {
            "club_ref": club_ref.strip(),
            "amount": validated_amount["amount"],
            "description": (description or "").strip(),
            "date": bill_date,
            "invoice": invoice_value,
            "member": resolved_member_name or member_id.strip(),
            "member_ref": member_ref_value,
            "premium": bool(premium) if premium is not None else False,
            "status": "Tertunggak",
        }
        if user_ref:
            data["user_ref"] = user_ref.strip()

        ref = db.collection(COLLECTION_BILLING).document()
        await ref.set(data)

        return {
            "status": "success",
            "bill_id": ref.id,
            "message": f"Bill of RM{validated_amount['amount']:.2f} issued to {data['member']}.",
        }

    except ValidationError as e:
        logger.warning(f"Validation error issuing bill: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error issuing bill: {e}")
        return {"status": "error", "error": str(e)}


async def update_bill_status(
    club_ref: str, bill_id: str, status: str
) -> Dict[str, Any]:
    """Updates the status of a bill.

    Args:
        club_ref: Reference to the club (for ownership verification)
        bill_id: ID of the bill to update
        status: New status ('Tertunggak', 'Dibayar', 'Batal', 'Sebahagian')

    Returns:
        Dict with status and message
    """
    try:
        # Validate inputs
        validate_text_field(bill_id, "Bill ID", min_length=1, max_length=100)
        validate_status(status, ALLOWED_BILL_STATUSES)

        # Verify bill exists and belongs to this club
        check = await read_club_data(
            club_ref=club_ref, collection="billing", doc_id=bill_id.strip()
        )
        if check["status"] == "error":
            return {"status": "error", "error": "Bill not found"}

        db = firestore.AsyncClient()
        ref = db.collection(COLLECTION_BILLING).document(bill_id.strip())
        await ref.update({"status": status.strip()})
        return {"status": "success", "message": f"Bill status updated to {status}."}

    except ValidationError as e:
        logger.warning(f"Validation error updating bill: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error updating bill: {e}")
        return {"status": "error", "error": str(e)}


async def issue_monthly_fees(
    club_ref: str, month: str, year: str, amount: float
) -> Dict[str, Any]:
    """Batch issues monthly fee bills to all members of the club."""
    try:
        # Get all active members via read_club_data
        members_result = await read_club_data(
            club_ref=club_ref,
            collection="member",
            limit=MAX_BATCH_SIZE,
        )
        if members_result["status"] == "error":
            return members_result

        members = members_result["data"]
        if not members:
            return {"status": "success", "message": "No active members found to bill."}

        db = firestore.AsyncClient()
        batch = db.batch()
        count = 0

        description = f"Yuran Bulanan {month} {year}"
        due_date = f"{year}-{month}-07"
        bill_date = validate_date(due_date)["parsed"]

        for member in members:
            ref = db.collection(COLLECTION_BILLING).document()
            data = {
                "club_ref": club_ref,
                "member": member.get("name") or member.get("id"),
                "member_ref": f"member/{member['id']}",
                "amount": float(amount),
                "description": description,
                "date": bill_date,
                "invoice": _generate_invoice(bill_date),
                "premium": False,
                "status": "Tertunggak",
            }
            batch.set(ref, data)
            count += 1

            # Firestore batch limit is 500. Commit in chunks of 400.
            if count % MAX_BATCH_SIZE == 0:
                await batch.commit()
                batch = db.batch()

        if count % MAX_BATCH_SIZE != 0:
            await batch.commit()

        return {
            "status": "success",
            "count": count,
            "message": f"Issued {count} bills for {description}.",
        }

    except Exception as e:
        logger.error(f"Error issuing monthly fees: {e}")
        return {"status": "error", "error": str(e)}
