"""Tools for managing shirts."""
import logging
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from ..constants import COLLECTION_SHIRTS
from .firestore_read import read_club_data

logger = logging.getLogger(__name__)


async def add_shirt_item(
    club_ref: str,
    name: str,
    price: float,
    count: int = 0,
    live: bool = True,
    img: Optional[List[str]] = None,
    variant: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Creates a shirt product item."""
    try:
        db = firestore.AsyncClient()

        data = {
            "club_ref": club_ref,
            "name": name,
            "price": float(price),
            "count": int(count),
            "live": bool(live),
            "img": img or [],
            "variant": variant or {},
        }

        ref = db.collection(COLLECTION_SHIRTS).document()
        await ref.set(data)

        return {
            "status": "success",
            "shirt_id": ref.id,
            "message": f"Shirt item '{name}' created successfully.",
        }

    except Exception as e:
        logger.error(f"Error adding shirt item: {e}")
        return {"status": "error", "error": str(e)}


async def update_shirt_item(
    club_ref: str, shirt_id: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Updates a shirt item (e.g., name, price, live).

    Args:
        club_ref: Reference to the club (for ownership verification)
        shirt_id: ID of the shirt item to update
        updates: Dict of field:value pairs to update
    """
    try:
        # Verify order exists and belongs to this club
        check = await read_club_data(
            club_ref=club_ref, collection="shirt", doc_id=shirt_id
        )
        if check["status"] == "error":
            return {"status": "error", "error": "Shirt item not found"}

        db = firestore.AsyncClient()
        ref = db.collection(COLLECTION_SHIRTS).document(shirt_id)
        await ref.update(updates)
        return {"status": "success", "message": "Shirt item updated."}

    except Exception as e:
        logger.error(f"Error updating shirt item: {e}")
        return {"status": "error", "error": str(e)}


# Backward-compatible aliases (deprecated)
async def add_shirt_order(
    club_ref: str,
    name: str,
    price: float,
    count: int = 0,
    live: bool = True,
    img: Optional[List[str]] = None,
    variant: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return await add_shirt_item(
        club_ref=club_ref,
        name=name,
        price=price,
        count=count,
        live=live,
        img=img,
        variant=variant,
    )


async def update_shirt_order(
    club_ref: str, shirt_id: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    return await update_shirt_item(
        club_ref=club_ref, shirt_id=shirt_id, updates=updates
    )
