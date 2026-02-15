"""Generic club-scoped Firestore read tool."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from ..constants import (
    ALLOWED_FILTER_OPS,
    COLLECTION_ALIASES,
    COLLECTION_CLUBS,
    COLLECTION_SESSIONS,
    DEFAULT_QUERY_LIMIT,
    MAX_BATCH_SIZE,
    READABLE_COLLECTIONS,
)
from .validation import ValidationError, validate_club_ref

logger = logging.getLogger(__name__)


def _resolve_collection(name: str) -> str:
    """Resolve a collection name or alias to the canonical Firestore collection name."""
    resolved = COLLECTION_ALIASES.get(name.lower().strip())
    if resolved is None or resolved not in READABLE_COLLECTIONS:
        available = sorted(set(COLLECTION_ALIASES.keys()))
        raise ValidationError(
            f"Unknown collection: '{name}'. Available: {', '.join(available)}"
        )
    return resolved


def _club_ref_field_for_collection(collection: str) -> str:
    """Return the club reference field name for a collection."""
    if collection == COLLECTION_SESSIONS:
        return "clubRef"
    return "club_ref"


def _sanitize_doc(data: dict) -> dict:
    """Convert Firestore-native types to JSON-safe representations."""
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, datetime):
            sanitized[key] = value.isoformat()
        elif hasattr(value, "path"):  # DocumentReference
            sanitized[key] = value.path
        elif isinstance(value, bytes):
            sanitized[key] = "<binary>"
        else:
            sanitized[key] = value
    return sanitized


def _club_ref_matches(stored_value: Any, expected_club_ref: str) -> bool:
    """Check if a stored club_ref value matches the expected string."""
    if isinstance(stored_value, str):
        return stored_value.strip() == expected_club_ref.strip()
    if hasattr(stored_value, "path"):  # DocumentReference
        return stored_value.path == expected_club_ref.strip()
    return str(stored_value) == expected_club_ref.strip()


def _validate_filters(filters: Optional[List[dict]]) -> None:
    """Validate the filters list structure and values."""
    if not filters:
        return
    for i, f in enumerate(filters):
        if not isinstance(f, dict):
            raise ValidationError(f"Filter {i} must be a dict, got {type(f).__name__}")
        missing = {"field", "op", "value"} - set(f.keys())
        if missing:
            raise ValidationError(f"Filter {i} missing keys: {', '.join(missing)}")
        if f["op"] not in ALLOWED_FILTER_OPS:
            raise ValidationError(
                f"Filter {i} has invalid op '{f['op']}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_FILTER_OPS))}"
            )
        if f["field"] in ("club_ref", "clubRef"):
            raise ValidationError(
                "Filtering on club reference is not allowed — club scoping is automatic."
            )


def _apply_fields(data: dict, fields: Optional[List[str]]) -> dict:
    """Project only the requested fields, always keeping 'id'."""
    if not fields:
        return data
    keep = set(fields) | {"id"}
    return {k: v for k, v in data.items() if k in keep}


async def read_club_data(
    club_ref: str,
    collection: str,
    doc_id: str = "",
    filters: Optional[List[dict]] = None,
    order_by: str = "",
    order_direction: str = "ASCENDING",
    limit: int = DEFAULT_QUERY_LIMIT,
    fields: Optional[List[str]] = None,
    count_only: bool = False,
) -> Dict[str, Any]:
    """Query any club-scoped Firestore data with enforced club scoping.

    Args:
        club_ref: Club document reference (e.g. "club/abc123"). Required.
        collection: Collection to query (member, sesi, billing, shirt, club).
        doc_id: Optional specific document ID to fetch.
        filters: Optional list of filter dicts [{"field", "op", "value"}].
        order_by: Optional field name to sort by.
        order_direction: "ASCENDING" or "DESCENDING".
        limit: Max results (default 50, max 400).
        fields: Optional list of field names to return (projection).
        count_only: If True, return only the count (no document data).

    Returns:
        {"status": "success", "data": [...], "count": N} or
        {"status": "success", "count": N} (count_only) or
        {"status": "error", "error": "message"}
    """
    try:
        # --- Validate inputs ---
        validate_club_ref(club_ref)
        club_ref = club_ref.strip()
        resolved = _resolve_collection(collection)
        limit = max(1, min(int(limit), MAX_BATCH_SIZE))

        if order_direction not in ("ASCENDING", "DESCENDING"):
            raise ValidationError(
                f"order_direction must be 'ASCENDING' or 'DESCENDING', "
                f"got '{order_direction}'"
            )

        _validate_filters(filters)

        db = firestore.AsyncClient()

        # --- Special case: club collection (single doc by club_ref) ---
        if resolved == COLLECTION_CLUBS:
            if "/" in club_ref:
                ref = db.document(club_ref)
            else:
                ref = db.collection(COLLECTION_CLUBS).document(club_ref)

            snapshot = await ref.get()
            if not snapshot.exists:
                return {"status": "error", "error": "Club not found"}

            data = _sanitize_doc(snapshot.to_dict())
            data["id"] = snapshot.id
            data = _apply_fields(data, fields)

            if count_only:
                return {"status": "success", "count": 1}
            return {"status": "success", "data": [data], "count": 1}

        # --- Single document get ---
        if doc_id and doc_id.strip():
            doc_id = doc_id.strip()
            ref = db.collection(resolved).document(doc_id)
            snapshot = await ref.get()

            if not snapshot.exists:
                return {"status": "error", "error": f"Document not found in {resolved}"}

            data = snapshot.to_dict()

            # Security: verify club_ref ownership
            stored_ref = data.get("club_ref")
            if stored_ref is None:
                stored_ref = data.get("clubRef")
            if stored_ref is None:
                return {"status": "error", "error": f"Document not found in {resolved}"}
            if not _club_ref_matches(stored_ref, club_ref):
                return {"status": "error", "error": f"Document not found in {resolved}"}

            data = _sanitize_doc(data)
            data["id"] = snapshot.id
            data = _apply_fields(data, fields)

            if count_only:
                return {"status": "success", "count": 1}
            return {"status": "success", "data": [data], "count": 1}

        # --- Collection query ---
        club_field = _club_ref_field_for_collection(resolved)

        def _build_query(field_name: str):
            q = db.collection(resolved).where(field_name, "==", club_ref)
            for f in (filters or []):
                q = q.where(f["field"], f["op"], f["value"])
            if order_by:
                direction = (
                    firestore.Query.DESCENDING
                    if order_direction == "DESCENDING"
                    else firestore.Query.ASCENDING
                )
                q = q.order_by(order_by, direction=direction)
            return q

        query = _build_query(club_field)

        if count_only:
            count_result = await query.count().get()
            count_val = count_result[0][0].value
            # Fallback for legacy sesi docs that used club_ref
            if resolved == COLLECTION_SESSIONS and club_field != "club_ref":
                fallback_query = _build_query("club_ref")
                fallback_count = await fallback_query.count().get()
                count_val += fallback_count[0][0].value
            return {"status": "success", "count": count_val}

        query = query.limit(limit)
        docs = await query.get()

        results_by_id = {}
        for doc in docs:
            d = _sanitize_doc(doc.to_dict())
            d["id"] = doc.id
            d = _apply_fields(d, fields)
            results_by_id[doc.id] = d

        # Fallback for legacy sesi docs that used club_ref
        if resolved == COLLECTION_SESSIONS and club_field != "club_ref" and len(results_by_id) < limit:
            fallback_query = _build_query("club_ref").limit(limit)
            fallback_docs = await fallback_query.get()
            for doc in fallback_docs:
                if doc.id in results_by_id:
                    continue
                d = _sanitize_doc(doc.to_dict())
                d["id"] = doc.id
                d = _apply_fields(d, fields)
                results_by_id[doc.id] = d

        results = list(results_by_id.values())

        return {"status": "success", "data": results, "count": len(results)}

    except ValidationError as e:
        logger.warning(f"Validation error in read_club_data: {e}")
        return {"status": "error", "error": f"Validation error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error in read_club_data: {e}")
        return {"status": "error", "error": str(e)}
