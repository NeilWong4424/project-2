"""FastAPI entry point for Cloud Run deployment."""
import os
import logging

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Register custom Firestore session service
from google.adk.cli.service_registry import get_service_registry
from app.services.firestore_session_service import FirestoreSessionService
from app.telegram_handler import TelegramBotHandler
from mybola_agent.agent import root_agent
from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Initialize Telegram bot handler at module level
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
APP_ENV = os.environ.get("APP_ENV", "production").lower()
telegram_handler = None
telegram_session_service = None

# Validate required environment variables early.
_required_env = [
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
]
if TELEGRAM_BOT_TOKEN:
    _required_env.append("TELEGRAM_BOT_TOKEN")

_missing_env = [key for key in _required_env if not os.environ.get(key)]
if _missing_env:
    logger.error(f"Missing required environment variables: {_missing_env}")
    if APP_ENV == "production":
        raise RuntimeError("Missing required environment variables")

if TELEGRAM_BOT_TOKEN:
    logger.info(f"TELEGRAM_BOT_TOKEN found, length: {len(TELEGRAM_BOT_TOKEN)}")
else:
    logger.warning("TELEGRAM_BOT_TOKEN not set - Telegram integration disabled")


def firestore_session_factory(uri: str, **kwargs) -> FirestoreSessionService:
    """Factory for creating FirestoreSessionService from URI.

    URI format: firestore://[project_id]/[database]
    Example: firestore:///  (uses env vars for project, default database)
    """
    return FirestoreSessionService(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        database="(default)",
        collection_prefix="adk",
    )


# Register the custom Firestore session service
get_service_registry().register_session_service("firestore", firestore_session_factory)

from fastapi import FastAPI
from contextlib import asynccontextmanager
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    await init_telegram()
    yield
    # Shutdown logic
    if telegram_handler:
        await telegram_handler.shutdown()

app = FastAPI(lifespan=lifespan)

# Rate limiting configuration
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors.

    Returns JSONResponse instead of raising exception.
    """
    logger.warning(f"Rate limit exceeded for {request.client.host}")
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": "Too many requests. Please try again later.",
            "retry_after": "60 seconds"
        }
    )


async def init_telegram():
    """Initialize Telegram bot."""
    global telegram_handler, telegram_session_service
    if TELEGRAM_BOT_TOKEN and telegram_handler is None:
        try:
            logger.info("Initializing Telegram bot with ADK agent...")

            # Create session service for Telegram
            telegram_session_service = FirestoreSessionService(
                project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                database="(default)",
                collection_prefix="adk",
            )

            telegram_handler = TelegramBotHandler(
                bot_token=TELEGRAM_BOT_TOKEN,
                agent=root_agent,
                session_service=telegram_session_service,
            )
            await telegram_handler.initialize()
            logger.info("Telegram bot initialized with ADK agent successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            import traceback
            logger.error(traceback.format_exc())


@app.post("/webhook/telegram")
@limiter.limit("30/minute")
async def telegram_webhook(request: Request):
    """Webhook endpoint for Telegram bot updates.

    Endpoint: POST /webhook/telegram
    """
    global telegram_handler

    # Lazy initialization on first webhook call
    if telegram_handler is None and TELEGRAM_BOT_TOKEN:
        await init_telegram()

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
    global telegram_handler

    # Lazy initialization on status check
    if telegram_handler is None and TELEGRAM_BOT_TOKEN:
        await init_telegram()

    if not telegram_handler or not telegram_handler.app:
        return {
            "status": "disabled",
            "message": "Telegram bot not configured",
            "token_present": bool(TELEGRAM_BOT_TOKEN),
            "token_length": len(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else 0,
        }

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


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz():
    """Basic health check for Cloud Run."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
