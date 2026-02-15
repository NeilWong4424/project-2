"""Tool for verifying if a user is a MyBola club owner."""
import logging
from typing import Any, Dict

from google.cloud import firestore

logger = logging.getLogger(__name__)

async def check_is_owner(user_id: str) -> Dict[str, Any]:
    """Checks if the provided user ID corresponds to a registered club owner.

    Args:
        user_id: The unique identifier of the user (from Telegram/Firebase auth).

    Returns:
        A dictionary containing:
        - is_owner (bool): True if the user is a club owner found in Firestore.
        - club_ref (str or None): The reference/ID of the club they own, if any.
        - club_name (str or None): The name of the club, if available.
        - error (str or None): Error message if something went wrong.
    """
    try:
        db = firestore.AsyncClient()
        
        # In a real app, user_id from Telegram might need mapping to Firebase Auth UID.
        # For this prototype, we assume user_id is directly usable or mappable.
        # Query users collection where telegram_id matches or document ID matches.
        # Assuming document ID is the user ID for simplicity in this MVP, 
        # OR we search for a field 'telegram_id'. 
        
        # Let's try to find a user document. 
        # First strategy: Check if user_id is a document key (Firebase UID).
        user_ref = db.collection("users").document(user_id)
        doc = await user_ref.get()
        
        if not doc.exists:
            # Second strategy: Query by telegram_id field if it exists
            query = db.collection("users").where("telegram_id", "==", user_id).limit(1)
            docs = await query.get()
            if not docs:
                return {"is_owner": False, "error": "User not found."}
            doc = docs[0]

        data = doc.to_dict()
        logger.info(f"Fetched user data: {data}")
        
        # Check explicit club_owner or club_admin flag
        if not (data.get("club_owner", False) or data.get("club_admin", False)):
             return {"is_owner": False, "error": "User is not a registered club admin."}
             
        club_ref = data.get("club_ref")
        logger.info(f"Found club_ref: {club_ref}")
        if not club_ref:
            return {"is_owner": False, "error": "Club owner flag is true, but no club_ref found."}

        # Resolve club name for better UX
        club_name = "Unknown Club"
        try:
             # club_ref might be a string path or a DocumentReference
             if isinstance(club_ref, str):
                 if "/" in club_ref:
                    club_doc = await db.document(club_ref).get()
                 else:
                    club_doc = await db.collection("club").document(club_ref).get()
             else:
                 club_doc = await club_ref.get()
                 
             if club_doc.exists:
                 club_data = club_doc.to_dict()
                 club_name = club_data.get("name", "Unknown Club")
        except Exception as e:
            logger.warning(f"Failed to fetch club details: {e}")

        return {
            "is_owner": True,
            "club_ref": str(club_ref), # Returning string representation
            "club_name": club_name
        }

    except Exception as e:
        import traceback
        logger.error(f"Error verifying owner: {e}\n{traceback.format_exc()}")
        return {"is_owner": False, "error": str(e)}
