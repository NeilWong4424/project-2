"""Sesi (Training Session) management tools for my-bola-0rl0yc Firebase project."""
import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore
import firebase_admin
from firebase_admin import messaging

logger = logging.getLogger(__name__)

# Initialize Firebase Admin SDK for my-bola-0rl0yc project
MYBOLA_PROJECT_ID = "my-bola-0rl0yc"

# Lazy initialization of clients
_firestore_client: Optional[firestore.Client] = None
_firebase_app: Optional[firebase_admin.App] = None


def _get_firestore_client() -> firestore.Client:
    """Get or create Firestore client for my-bola project."""
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client(project=MYBOLA_PROJECT_ID)
        logger.info(f"Initialized Firestore client for {MYBOLA_PROJECT_ID}")
    return _firestore_client


def _get_firebase_app() -> firebase_admin.App:
    """Get or create Firebase Admin app for my-bola project (as default app)."""
    global _firebase_app
    if _firebase_app is None:
        try:
            # Try to get existing default app
            _firebase_app = firebase_admin.get_app()
        except ValueError:
            # Initialize as default app (required for messaging module)
            _firebase_app = firebase_admin.initialize_app(
                options={"projectId": MYBOLA_PROJECT_ID},
            )
            logger.info(f"Initialized Firebase Admin app for {MYBOLA_PROJECT_ID}")
    return _firebase_app


def _get_club_by_name(club_name: str) -> Optional[tuple]:
    """Lookup club document by name field.

    Args:
        club_name: The club's name (e.g., "FC Tigers")

    Returns:
        Tuple of (club_reference, club_data) if found, None otherwise
    """
    db = _get_firestore_client()
    clubs = db.collection("club").where("name", "==", club_name).limit(1).stream()
    club_doc = next(clubs, None)
    if club_doc is None:
        return None
    return club_doc.reference, club_doc.to_dict()


def create_sesi(
    name: str,
    location: str,
    date: str,
    duration: int,
    price: int,
    age_group: str,
    club_name: str,
) -> dict:
    """Creates a new training session (Sesi) and notifies club members.

    Args:
        name: Session name (e.g., "Latihan Pagi", "Morning Training")
        location: Where the session will be held
        date: Date and time in ISO format (e.g., "2026-02-01T09:00:00")
        duration: Duration in minutes
        price: Session price in MYR
        age_group: Target age group (e.g., "U12", "U15", "Senior")
        club_name: The club's name (e.g., "FC Tigers", "Kelab Bola Sepak KL")

    Returns:
        dict with status, message, and sesi_id if successful
    """
    try:
        db = _get_firestore_client()

        # Parse date
        session_date = datetime.fromisoformat(date)

        # Lookup club by name
        club_result = _get_club_by_name(club_name)
        if club_result is None:
            return {"status": "error", "message": f"Club '{club_name}' not found. Please check the club name."}

        club_ref, club_data = club_result

        # Create sesi document
        sesi_data = {
            "name": name,
            "location": location,
            "date": session_date,
            "duration": duration,
            "price": price,
            "age_group": age_group,
            "club_ref": club_ref,
            "member": [],  # Initialize with empty members list
            "createdAt": firestore.SERVER_TIMESTAMP,
        }

        # Add to Firestore
        _, doc_ref = db.collection("sesi").add(sesi_data)
        sesi_id = doc_ref.id

        logger.info(f"Created sesi '{name}' with ID: {sesi_id}")

        # Send push notification to club members
        notification_result = _send_push_notification(
            club_name=club_name,
            club_ref=club_ref,
            title=club_data.get("name", club_name),
            body=f"{name} akan dijalankan di {location} pada {session_date.strftime('%I:%M %p %d/%m/%y')}. Sila tandakan kehadiran anda.",
        )

        return {
            "status": "success",
            "message": f"Session '{name}' created successfully",
            "sesi_id": sesi_id,
            "notification": notification_result,
        }

    except ValueError as e:
        return {"status": "error", "message": f"Invalid date format: {e}"}
    except Exception as e:
        logger.error(f"Error creating sesi: {e}")
        return {"status": "error", "message": str(e)}


def list_sesi(club_name: str, limit: int = 10) -> dict:
    """Lists upcoming sessions for a club.

    Args:
        club_name: The club's name (e.g., "FC Tigers")
        limit: Maximum number of sessions to return (default: 10)

    Returns:
        dict with status and list of sessions
    """
    try:
        db = _get_firestore_client()

        # Lookup club by name
        club_result = _get_club_by_name(club_name)
        if club_result is None:
            return {"status": "error", "message": f"Club '{club_name}' not found. Please check the club name."}

        club_ref, _ = club_result

        # Query sessions for this club, ordered by date
        query = (
            db.collection("sesi")
            .where("club_ref", "==", club_ref)
            .where("date", ">=", datetime.now(timezone.utc))
            .order_by("date")
            .limit(limit)
        )

        sessions = []
        for doc in query.stream():
            data = doc.to_dict()
            date_value = data.get("date")
            # Handle both Firestore Timestamp and datetime objects
            if hasattr(date_value, "isoformat"):
                date_str = date_value.isoformat()
            elif hasattr(date_value, "to_datetime"):
                date_str = date_value.to_datetime().isoformat()
            else:
                date_str = None
            sessions.append({
                "id": doc.id,
                "name": data.get("name"),
                "location": data.get("location"),
                "date": date_str,
                "duration": data.get("duration"),
                "price": data.get("price"),
                "age_group": data.get("age_group"),
            })

        return {
            "status": "success",
            "count": len(sessions),
            "sessions": sessions,
        }

    except Exception as e:
        logger.error(f"Error listing sesi: {e}")
        return {"status": "error", "message": str(e)}


def update_sesi(
    club_name: str,
    session_date: str,
    name: Optional[str] = None,
    location: Optional[str] = None,
    new_date: Optional[str] = None,
    duration: Optional[int] = None,
    price: Optional[int] = None,
    age_group: Optional[str] = None,
) -> dict:
    """Updates an existing session identified by club name and session datetime.

    Args:
        club_name: The club's name (e.g., "FC Tigers")
        session_date: The session's current date/time in ISO format (e.g., "2026-02-01T09:00:00")
        name: New session name (optional)
        location: New location (optional)
        new_date: New date in ISO format (optional) - use this to change the session time
        duration: New duration in minutes (optional)
        price: New price in MYR (optional)
        age_group: New age group (optional)

    Returns:
        dict with status and message
    """
    try:
        db = _get_firestore_client()

        # Lookup club by name
        club_result = _get_club_by_name(club_name)
        if club_result is None:
            return {"status": "error", "message": f"Club '{club_name}' not found. Please check the club name."}

        club_ref, _ = club_result

        # Parse the session date to find the session
        target_date = datetime.fromisoformat(session_date)

        # Find session by club + date
        query = (
            db.collection("sesi")
            .where("club_ref", "==", club_ref)
            .where("date", "==", target_date)
            .limit(1)
        )

        docs = list(query.stream())
        if not docs:
            return {"status": "error", "message": f"No session found for '{club_name}' on {session_date}"}

        doc_ref = docs[0].reference
        old_session_name = docs[0].to_dict().get("name", "Session")

        # Build update data
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if location is not None:
            update_data["location"] = location
        if new_date is not None:
            update_data["date"] = datetime.fromisoformat(new_date)
        if duration is not None:
            update_data["duration"] = duration
        if price is not None:
            update_data["price"] = price
        if age_group is not None:
            update_data["age_group"] = age_group

        if not update_data:
            return {"status": "error", "message": "No fields to update"}

        update_data["updatedAt"] = firestore.SERVER_TIMESTAMP

        # Update document
        doc_ref.update(update_data)

        logger.info(f"Updated sesi '{old_session_name}' for {club_name} with fields: {list(update_data.keys())}")

        return {
            "status": "success",
            "message": f"Session '{old_session_name}' updated successfully",
            "updated_fields": list(update_data.keys()),
        }

    except ValueError as e:
        return {"status": "error", "message": f"Invalid date format: {e}"}
    except Exception as e:
        logger.error(f"Error updating sesi: {e}")
        return {"status": "error", "message": str(e)}


def delete_sesi(club_name: str, session_date: str) -> dict:
    """Deletes a session identified by club name and session datetime.

    Args:
        club_name: The club's name (e.g., "FC Tigers")
        session_date: The session's date/time in ISO format (e.g., "2026-02-01T09:00:00")

    Returns:
        dict with status and message
    """
    try:
        db = _get_firestore_client()

        # Lookup club by name
        club_result = _get_club_by_name(club_name)
        if club_result is None:
            return {"status": "error", "message": f"Club '{club_name}' not found. Please check the club name."}

        club_ref, _ = club_result

        # Parse the session date
        target_date = datetime.fromisoformat(session_date)

        # Find session by club + date
        query = (
            db.collection("sesi")
            .where("club_ref", "==", club_ref)
            .where("date", "==", target_date)
            .limit(1)
        )

        docs = list(query.stream())
        if not docs:
            return {"status": "error", "message": f"No session found for '{club_name}' on {session_date}"}

        doc_ref = docs[0].reference
        session_name = docs[0].to_dict().get("name", "Session")

        # Delete document
        doc_ref.delete()

        logger.info(f"Deleted sesi '{session_name}' for {club_name} on {session_date}")

        return {
            "status": "success",
            "message": f"Session '{session_name}' deleted successfully",
        }

    except Exception as e:
        logger.error(f"Error deleting sesi: {e}")
        return {"status": "error", "message": str(e)}


def _send_push_notification(
    club_name: str,
    club_ref,
    title: str,
    body: str,
) -> dict:
    """Sends push notification to all club members.

    Args:
        club_name: Club name for logging
        club_ref: Club document reference
        title: Notification title
        body: Notification body text

    Returns:
        dict with notification status
    """
    try:
        db = _get_firestore_client()
        _get_firebase_app()  # Ensure Firebase app is initialized for messaging

        # Query users with matching club_ref
        users_query = db.collection("users").where("club_ref", "==", club_ref)

        # Collect FCM tokens
        tokens = []
        for user_doc in users_query.stream():
            user_data = user_doc.to_dict()
            fcm_token = user_data.get("fcmToken") or user_data.get("fcm_token")
            if fcm_token:
                tokens.append(fcm_token)

        if not tokens:
            logger.info(f"No FCM tokens found for club '{club_name}'")
            return {"sent": 0, "message": "No members with FCM tokens found"}

        # Send multicast message
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data={
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
                "type": "sesi_created",
            },
            tokens=tokens,
            android=messaging.AndroidConfig(
                notification=messaging.AndroidNotification(
                    sound="default",
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default"),
                ),
            ),
        )

        response = messaging.send_each_for_multicast(message)

        logger.info(
            f"Push notification sent: {response.success_count} success, {response.failure_count} failed"
        )

        return {
            "sent": response.success_count,
            "failed": response.failure_count,
            "total_tokens": len(tokens),
        }

    except Exception as e:
        logger.error(f"Error sending push notification: {e}")
        return {"sent": 0, "error": str(e)}
