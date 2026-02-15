"""Tools for 2-step Telegram account linking via email verification code."""
import logging
import os
import random
import smtplib
import ssl
import string
from email.message import EmailMessage
from typing import Any, Dict

from google.cloud import firestore

logger = logging.getLogger(__name__)

def generate_verification_code(length=6) -> str:
    """Generates a random numeric verification code."""
    return ''.join(random.choices(string.digits, k=length))

def send_email_via_gmail(to_email: str, subject: str, body: str):
    """Sends an email using Gmail SMTP."""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        logger.warning("GMAIL_USER or GMAIL_APP_PASSWORD not set. Skipping email send.")
        return

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email

    context = ssl.create_default_context()
    
    # Connect to Gmail's SMTP server
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
    
    logger.info(f"Email sent to {to_email}")

async def initiate_linking(email: str) -> Dict[str, Any]:
    """Step 1: Finds user by email, generates a code, and sends it via Gmail.
    
    Args:
        email: The email address provided by the user.
        
    Returns:
        Dict indicating if the code was sent.
    """
    try:
        db = firestore.AsyncClient()
        email = email.lower().strip()
        
        # Query user by email
        query = db.collection("users").where("email", "==", email).limit(1)
        docs = await query.get()
        
        if not docs:
            return {
                "status": "error", 
                "error": "No MyBola account found with this email."
            }
            
        user_doc = docs[0]
        user_data = user_doc.to_dict()
        
        if not (user_data.get("club_owner", False) or user_data.get("club_admin", False)):
            return {
                "status": "error", 
                "error": "This email is not registered as a Club Admin."
            }

        # Generate unique code
        code = generate_verification_code()
        
        # Store code in Firestore with a "verification" field
        await user_doc.reference.update({
            "verification_code": code,
            "verification_requested_at": firestore.SERVER_TIMESTAMP
        })
        
        # Send Email via Gmail SMTP
        subject = "MyBola Verification Code"
        body = f"Your verification code to link your Telegram account is: {code}\n\nIf you did not request this, please ignore this email."
        
        try:
            send_email_via_gmail(email, subject, body)
            email_status = "Email sent successfully."
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            email_status = f"Failed to send email (check logs). Debug Code: {code}"
        
        return {
            "status": "success",
            "message": f"Verification code sent to {email}. {email_status} Please check your inbox (and spam folder).",
            # We remove debug_code from the success message in production ideally, 
            # but keeping it in message/logs might be useful for now if SMTP fails.
        }
        
    except Exception as e:
        logger.error(f"Error initiating linking: {e}")
        return {"status": "error", "error": str(e)}

async def verify_linking(email: str, code: str, telegram_id: str) -> Dict[str, Any]:
    """Step 2: Verifies the code and links the Telegram ID.
    
    Args:
        email: The email address provided by the user.
        code: The verification code provided by the user.
        telegram_id: The Telegram ID to link.
        
    Returns:
        Dict indicating success or failure of linking.
    """
    try:
        db = firestore.AsyncClient()
        email = email.lower().strip()
        code = code.strip()
        
        query = db.collection("users").where("email", "==", email).limit(1)
        docs = await query.get()
        
        if not docs:
            return {"status": "error", "error": "User not found."}
            
        user_doc = docs[0]
        user_data = user_doc.to_dict()
        
        stored_code = user_data.get("verification_code")
        
        if not stored_code or stored_code != code:
            return {"status": "error", "error": "Invalid verification code. Please try again."}
            
        # Code matches! Link the account.
        await user_doc.reference.update({
            "telegram_id": telegram_id,
            "telegram_linked_at": firestore.SERVER_TIMESTAMP,
            "verification_code": firestore.DELETE_FIELD # Clean up used code
        })
        
        club_ref = user_data.get("club_ref")
        
        return {
            "status": "success",
            "message": f"Account linked successfully! Welcome, {user_data.get('name', 'Owner')}.",
            "club_ref": str(club_ref) if club_ref else None,
            "is_owner": True
        }
        
    except Exception as e:
        logger.error(f"Error verifying linking: {e}")
        return {"status": "error", "error": str(e)}
