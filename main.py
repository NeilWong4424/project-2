"""FastAPI entry point for Cloud Run deployment."""
import os
import logging

from fastapi import Request, HTTPException
from telegram import Update

# Register custom Firestore session service
from google.adk.cli.service_registry import get_service_registry
from firestore_session_service import FirestoreSessionService
from telegram_handler import TelegramBotHandler

logger = logging.getLogger(__name__)


def firestore_session_factory(uri: str, **kwargs) -> FirestoreSessionService:
    """Factory for creating FirestoreSessionService from URI.

    URI format: firestore://[project_id]/[database]
    Example: firestore:///  (uses env vars for project, default database)
    """
    return FirestoreSessionService(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        database="project2",
        collection_prefix="adk",
    )


# Register the custom Firestore session service
get_service_registry().register_session_service("firestore", firestore_session_factory)

from google.adk.cli.fast_api import get_fast_api_app

# Get the directory where main.py is located (project root)
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Get the FastAPI app from ADK with Firestore session service
app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri="firestore:///",  # Uses custom FirestoreSessionService
    web=True,  # Enable ADK dev UI
)

# Initialize Telegram bot handler
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
telegram_handler = None


@app.on_event("startup")
async def startup_telegram():
    """Initialize Telegram bot on startup."""
    global telegram_handler
    if TELEGRAM_BOT_TOKEN:
        telegram_handler = TelegramBotHandler(
            bot_token=TELEGRAM_BOT_TOKEN,
            agent_session_service=None,  # Will be integrated with agent
        )
        await telegram_handler.initialize()
        logger.info("Telegram bot initialized")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set - Telegram integration disabled")


@app.on_event("shutdown")
async def shutdown_telegram():
    """Shutdown Telegram bot on shutdown."""
    global telegram_handler
    if telegram_handler:
        await telegram_handler.shutdown()
        logger.info("Telegram bot shutdown")


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Webhook endpoint for Telegram bot updates.

    Endpoint: POST /webhook/telegram
    """
    if not telegram_handler:
        raise HTTPException(
            status_code=503, detail="Telegram bot not configured"
        )

    try:
        update_data = await request.json()
        await telegram_handler.handle_webhook(update_data)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {e}")
        raise HTTPException(status_code=400, detail="Failed to process update")


@app.get("/telegram/webhook-status")
async def telegram_webhook_status():
    """Get Telegram webhook status."""
    if not telegram_handler or not telegram_handler.app:
        return {"status": "disabled", "message": "Telegram bot not configured"}

    try:
        bot_info = await telegram_handler.app.bot.get_me()
        return {
            "status": "active",
            "bot_username": bot_info.username,
            "bot_name": bot_info.first_name,
        }
    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
