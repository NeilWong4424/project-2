"""Telegram bot webhook handler for ADK agent integration.

This module is the bridge between Telegram and the ADK (Agent Development Kit)
agent.  It receives messages from Telegram users (via webhooks), routes them to
the appropriate handler, forwards them to the AI agent, and sends the agent's
reply back to the user.

Architecture overview:
  Telegram Cloud  ──webhook POST──►  Cloud Run (main.py)
                                        │
                                        ▼
                                  TelegramBotHandler.handle_webhook()
                                        │
                          ┌─────────────┼──────────────┐
                          ▼             ▼              ▼
                    /command        /summary, /bills...   free text / voice
                    (system menu)   (agent cmd)          (agent message)
                    (own logic)     (raw /command)
                          │             │              │
                          └─────────────┼──────────────┘
                                        ▼
                              _get_agent_response()
                                        │
                                        ▼
                              ADK Runner.run_async()
                                        │
                                        ▼
                              Agent processes + tool calls
                                        │
                                        ▼
                              Response sent back to Telegram

Key design decisions:
  - Every slash command (e.g. /members, /bills) is forwarded as raw text to the
    agent. This keeps the bot logic thin and lets the agent decide what to do.
  - Onboarding happens inside the agent when no verification context exists.
    The handler only checks/caches verification and injects system context.
  - Unverified users are temporarily negative-cached to reduce repeated
    Firestore reads within a short time window.
  - Voice messages are transcribed by Gemini before being sent to the agent.
  - Rate-limited (429) requests from Vertex AI are retried with exponential
    backoff to handle quota spikes gracefully.
  - Sessions are keyed by Telegram user ID so each user gets their own
    conversation thread.

User experience flow (high level):
  1) User sends a message or slash command.
  2) If unverified, the agent starts onboarding (email + code).
  3) If verified, the agent handles the request immediately.
  4) /command shows the full menu; other slash commands are forwarded as raw text.
  5) Voice notes are transcribed and then handled like text.
"""
import logging
import tempfile
import os
import asyncio
import random
import time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google.adk.runners import Runner
from google.genai import types
from google import genai
from google.api_core import exceptions as api_exceptions

from mybola_agent.tools.owner_verification import check_is_owner
from app.metrics import MESSAGE_TOTAL, COMMAND_TOTAL, AGENT_LATENCY, AGENT_ERRORS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration for Vertex AI rate limits (HTTP 429)
# ---------------------------------------------------------------------------
# Vertex AI has per-minute quotas.  When the agent or transcription call
# exceeds the quota, the API returns a 429 / RESOURCE_EXHAUSTED error.
# We retry with exponential backoff: ~2s, 4s, 8s, 16s ≈ 30s total,
# which comfortably fits within Cloud Run's default 60s request timeout.
_MAX_RETRIES = 4
_BASE_RETRY_DELAY = 2  # seconds
# Avoid repeated Firestore lookups for unverified users within a short window.
_UNVERIFIED_CACHE_TTL = 300  # seconds
# Simple circuit breaker for repeated agent failures.
_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_TIMEOUT = 30  # seconds
_AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "45"))


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a Vertex AI rate limit (429) error.

    We check both the typed exception class AND the string representation
    because some errors come wrapped in generic exceptions.
    """
    if isinstance(exc, api_exceptions.ResourceExhausted):
        return True
    err_str = str(exc)
    return "RESOURCE_EXHAUSTED" in err_str or "429" in err_str


# Parse HELP_MENU so the menu itself stays the single source of truth.
def _extract_command_names(help_menu: str) -> list[str]:
    """Extract slash command names from the help menu."""
    names: list[str] = []
    seen: set[str] = set()
    for line in help_menu.splitlines():
        line = line.strip()
        if not line.startswith("/"):
            continue
        command = line[1:].split(maxsplit=1)[0]
        if command and command not in seen:
            names.append(command)
            seen.add(command)
    return names


class TelegramBotHandler:
    """Handler for Telegram bot webhook integration with ADK agent."""

    # ---------------------------------------------------------------------------
    # Command definitions
    # ---------------------------------------------------------------------------
    # Single source of truth for the command menu.
    # If you add/remove commands, update HELP_MENU below.
    # The agent (mybola_agent/agent.py) does NOT have its own copy - it tells
    # users to type /command instead.
    HELP_MENU = """Here are all available commands:

📊 Dashboard
/summary - Club overview
/overdue - Overdue payments

👥 Members
/members - List all members
/register - Register a new member
/updatemember - Update member info
/archivemember - Archive a member

⚽ Training
/sessions - Upcoming sessions
/newsession - Schedule a new training
/updatesession - Update a session
/deletesession - Delete a session

💰 Finance
/bills - View all bills
/newbill - Issue a bill
/monthlyfees - Issue monthly fees
/updatebill - Update bill status

🏟️ Club
/registerclub - Register a new club
/club - View club details
/updateclub - Update club info
/inviteadmin - Invite a club admin
/removeadmin - Remove a club admin

👕 Merchandise
/orders - View merchandise orders
/neworder - Record a merchandise order
/updateorder - Update an order

🔧 System
/command - Show this menu
/link - Link your account

💡 Tip: You can also just type what you need in plain text!"""

    # Commands handled locally (not forwarded to the agent).
    SYSTEM_COMMANDS = {"command"}
    # Derive agent-forwarded commands directly from HELP_MENU to avoid drift.
    COMMAND_NAMES = []
    for name in _extract_command_names(HELP_MENU):
        if name not in SYSTEM_COMMANDS:
            COMMAND_NAMES.append(name)

    def __init__(self, bot_token: str, agent, session_service):
        """Initialize Telegram bot handler.

        Note: This only stores references.  The actual Telegram Application
        and ADK Runner are created later in initialize() because they require
        async setup.

        Args:
            bot_token: Telegram bot token (from @BotFather).
            agent: ADK agent instance (the AI brain — see mybola_agent/).
            session_service: FirestoreSessionService for persisting conversations.
        """
        self.bot_token = bot_token
        self.agent = agent
        self.session_service = session_service
        self.app = None       # python-telegram-bot Application (created in initialize)
        self.runner = None    # ADK Runner that orchestrates agent execution
        # In-memory verification cache: telegram_user_id → {club_ref, club_name}.
        # Avoids calling check_is_owner (Firestore read) on every message.
        # Resets naturally on Cloud Run cold starts — no explicit TTL needed.
        self._verified_users: dict[str, dict] = {}
        # Negative cache for unverified users to reduce repeated Firestore reads.
        # Maps telegram_user_id → last checked timestamp (epoch seconds).
        self._unverified_users: dict[str, float] = {}
        # Concurrency limit for agent calls (protects downstream services).
        max_concurrency = int(os.environ.get("AGENT_CONCURRENCY", "10"))
        self._agent_semaphore = asyncio.Semaphore(max_concurrency)
        # Circuit breaker state for repeated agent failures.
        self._agent_failures = 0
        self._circuit_open_until = 0.0

    async def initialize(self):
        """Initialize Telegram application and register all handlers.

        Called once at startup (from main.py).  Sets up:
          1. The python-telegram-bot Application (manages bot API connection).
          2. The ADK Runner (bridges user messages → agent → tool calls → response).
          3. All command and message handlers (routing table).
        """
        self.app = Application.builder().token(self.bot_token).build()

        # Create the ADK Runner — it takes a user message, runs the agent,
        # and streams back events (which contain the agent's response).
        if self.agent and self.session_service:
            self.runner = Runner(
                agent=self.agent,
                app_name="mybola_agent",
                session_service=self.session_service,
            )
            logger.info("ADK Runner initialized for Telegram")

        # --- Handler registration (order matters!) ---
        # python-telegram-bot checks handlers top-to-bottom; first match wins.

        # 1. System commands — handled directly, not forwarded to the agent.
        self.app.add_handler(CommandHandler("command", self.command_menu))

        # 2. Agent-forwarded commands - each /command is forwarded as raw text
        #    to the agent.
        for cmd_name in self.COMMAND_NAMES:
            self.app.add_handler(
                CommandHandler(cmd_name, self._make_command_handler(cmd_name))
            )

        # 3. Free-form text messages (anything that isn't a /command).
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        # 4. Voice notes and audio files — transcribed first, then sent to agent.
        self.app.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self.handle_audio_message)
        )

        # Finalize the Application (opens the HTTP connection to Telegram).
        await self.app.initialize()

    async def shutdown(self):
        """Shutdown Telegram application and release resources."""
        if self.app:
            await self.app.stop()

    # ------------------------------------------------------------------
    # Pre-verification helpers
    # ------------------------------------------------------------------

    async def _check_verification(self, user_id: str) -> dict | None:
        """Check if a user is a verified club owner, using cache then Firestore.

        Returns:
            Dict with {club_ref, club_name} if verified, None otherwise.
        """
        # Fast path: cache hit
        if user_id in self._verified_users:
            return self._verified_users[user_id]

        # Negative cache: avoid repeated Firestore hits for recently-unverified users.
        last_checked = self._unverified_users.get(user_id)
        if last_checked and (time.time() - last_checked) < _UNVERIFIED_CACHE_TTL:
            return None

        # Slow path: cache miss — query Firestore via the existing tool function
        result = await check_is_owner(user_id)

        if result.get("is_owner"):
            verification_data = {
                "club_ref": result["club_ref"],
                "club_name": result.get("club_name", "Unknown Club"),
            }
            self._verified_users[user_id] = verification_data
            self._unverified_users.pop(user_id, None)
            logger.info(f"User {user_id} verified and cached: {verification_data['club_name']}")
            return verification_data

        self._unverified_users[user_id] = time.time()
        return None

    def _prepend_verification_context(self, message: str, verification: dict) -> str:
        """Prepend verification context to a message so the agent knows
        the user is already verified and which club they belong to."""
        context = (
            f"[SYSTEM CONTEXT — DO NOT REPEAT TO USER] "
            f"User is verified. club_ref={verification['club_ref']}, "
            f"club_name={verification['club_name']}. "
            f"Do NOT call check_is_owner. Proceed directly with the user's request.\n\n"
        )
        return context + message

    async def _try_cache_after_linking(self, user_id: str) -> None:
        """After an unverified user interacts with the agent, check if they
        just completed account linking and should now be cached.

        Called after the agent response for unverified users. If verify_linking
        just wrote telegram_id to Firestore, check_is_owner will now return
        is_owner=True and we cache them for future messages.
        """
        try:
            result = await check_is_owner(user_id)
            if result.get("is_owner"):
                verification_data = {
                    "club_ref": result["club_ref"],
                    "club_name": result.get("club_name", "Unknown Club"),
                }
                self._verified_users[user_id] = verification_data
                self._unverified_users.pop(user_id, None)
                logger.info(f"User {user_id} newly verified after linking, cached")
        except Exception as e:
            logger.warning(f"Failed to check verification after linking for {user_id}: {e}")

    # ------------------------------------------------------------------
    # System command handlers (menu only)
    # ------------------------------------------------------------------

    async def command_menu(self, update: Update, _context: ContextTypes.DEFAULT_TYPE):
        """Handle /command - show full categorized command menu."""
        if not update.message:
            logger.warning("Received /command without message payload")
            return
        MESSAGE_TOTAL.labels(type="command").inc()
        COMMAND_TOTAL.labels(command="command").inc()
        await update.message.reply_text(self.HELP_MENU)

    # ------------------------------------------------------------------
    # Agent-forwarded command infrastructure
    # ------------------------------------------------------------------

    def _make_command_handler(self, cmd_name: str):
        """Factory: create a handler closure for a single slash command.

        This is called once per command during initialize(). It forwards
        the raw /command text to _command_to_agent().

        Args:
            cmd_name: The command name (without /) matching a known command.
        """
        async def handler(update: Update, _context: ContextTypes.DEFAULT_TYPE):
            await self._command_to_agent(update)

        return handler

    async def _command_to_agent(self, update: Update):
        """Forward a slash command to the agent as raw text.

        The raw text (e.g. "/register Ali") is sent to the agent unchanged.
        """
        if not update.message:
            logger.warning("Received command without message payload")
            return
        user_id = str(update.effective_user.id)

        raw_text = update.message.text or ""
        command_name = raw_text.split(maxsplit=1)[0].lstrip("/") if raw_text else "unknown"
        MESSAGE_TOTAL.labels(type="command").inc()
        COMMAND_TOTAL.labels(command=command_name or "unknown").inc()

        try:
            await update.message.chat.send_action("typing")

            if self.runner and self.session_service:
                response_text = await self._get_agent_response(user_id, raw_text)
            else:
                response_text = "Agent not configured."

            await self._send_response(update, response_text)

        except Exception as e:
            logger.error(f"Error processing command for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text(
                "Sorry, I encountered an error. Please try again."
            )

    async def _send_response(self, update: Update, response_text: str):
        """Send a response, splitting if it exceeds Telegram's 4096-char limit.

        Telegram's sendMessage API rejects messages longer than 4096 characters.
        If the agent's response is longer, we split it into consecutive chunks.
        """
        if not update.message:
            logger.warning("Cannot send response: missing message payload")
            return
        if not response_text:
            response_text = "I received your request but couldn't generate a response."

        if len(response_text) > 4096:
            # Naive split at 4096 boundaries — could break mid-word, but
            # good enough for agent responses which are usually well under limit.
            for chunk in [response_text[i:i + 4096] for i in range(0, len(response_text), 4096)]:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(response_text)

    # ------------------------------------------------------------------
    # Free-form message handlers
    # ------------------------------------------------------------------

    async def handle_message(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle free-form text messages (not slash commands).

        This is the most common path — the user just types something like
        "Show me overdue payments for Ahmad" and it goes straight to the agent.
        """
        if not update.message:
            logger.warning("Received text update without message payload")
            return
        user_id = str(update.effective_user.id)
        user_message = update.message.text
        MESSAGE_TOTAL.labels(type="text").inc()

        try:
            await update.message.chat.send_action("typing")

            logger.info(
                f"Processing Telegram message from {user_id}: {user_message[:50]}"
            )

            # Forward the raw text to the agent — no prompt transformation needed
            if self.runner and self.session_service:
                response_text = await self._get_agent_response(user_id, user_message)
            else:
                response_text = f"Agent not configured. Your message: {user_message}"

            await self._send_response(update, response_text)

        except Exception as e:
            logger.error(f"Error processing Telegram message: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text(
                "Sorry, I encountered an error. Please try again."
            )

    async def handle_audio_message(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle incoming voice/audio messages from Telegram users.

        Flow:
          1. Download the audio file from Telegram's servers to a temp file.
          2. Send the audio to Gemini for speech-to-text transcription.
          3. Echo the transcription back to the user (so they can verify).
          4. Forward the transcribed text to the agent, just like a text message.
          5. Clean up the temp file regardless of success/failure.
        """
        if not update.message:
            logger.warning("Received audio update without message payload")
            return
        user_id = str(update.effective_user.id)
        MESSAGE_TOTAL.labels(type="audio").inc()

        try:
            await update.message.chat.send_action("typing")

            # Telegram sends voice notes as .voice, uploaded audio files as .audio
            if update.message.voice:
                audio_file = update.message.voice
                file_type = "voice"
            else:
                audio_file = update.message.audio
                file_type = "audio"

            logger.info(
                f"Processing {file_type} message from {user_id}, "
                f"file_id: {audio_file.file_id}, duration: {audio_file.duration}s"
            )

            # Step 1: Download from Telegram to a local temp file.
            # Telegram stores files on their servers; we need a local copy
            # to send to Gemini.
            file = await self.app.bot.get_file(audio_file.file_id)

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
                tmp_path = tmp_file.name
                await file.download_to_drive(tmp_path)

            try:
                # Step 2: Transcribe audio → text using Gemini.
                transcribed_text = await self._transcribe_audio(tmp_path)

                if not transcribed_text:
                    await update.message.reply_text(
                        "I couldn't understand the audio. Please try again or send a text message."
                    )
                    return

                logger.info(f"Transcribed audio: {transcribed_text[:100]}...")

                # Step 3: Show the user what we heard (transparency).
                await update.message.reply_text(f"🎤 I heard: \"{transcribed_text}\"")

                # Step 4: Forward transcription to the agent as if the user typed it.
                await update.message.chat.send_action("typing")

                if self.runner and self.session_service:
                    response_text = await self._get_agent_response(user_id, transcribed_text)
                else:
                    response_text = f"Agent not configured. Your message: {transcribed_text}"

                await self._send_response(update, response_text)

            finally:
                # Step 5: Always clean up the temp file (even on errors).
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except Exception as e:
            logger.error(f"Error processing audio message: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text(
                "Sorry, I couldn't process your audio message. Please try again or send a text message."
            )

    async def _transcribe_audio(self, audio_path: str) -> str:
        """Transcribe an audio file to text using Gemini's multimodal capability.

        Instead of a dedicated speech-to-text API, this uses Gemini's ability
        to understand audio content.  The audio bytes are sent inline (not
        uploaded to GCS) because Vertex AI's files.upload isn't available in
        all environments.

        Args:
            audio_path: Local filesystem path to the .ogg audio file.

        Returns:
            The transcribed text, or "" if transcription failed.
        """
        # Create a Gemini client pointing at Vertex AI (not the public API)
        client = genai.Client(vertexai=True)

        # Read the entire audio file into memory (voice notes are small)
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        for attempt in range(_MAX_RETRIES + 1):
            try:
                # Send audio + transcription prompt to Gemini as a multimodal request
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                # The audio bytes (inline, not a GCS URI)
                                types.Part.from_bytes(
                                    data=audio_data,
                                    mime_type="audio/ogg",
                                ),
                                # The instruction telling Gemini what to do
                                types.Part.from_text(
                                    text="Please transcribe this audio message accurately. "
                                    "Return only the transcription, nothing else. "
                                    "If the audio is unclear or empty, return an empty string."
                                ),
                            ],
                        )
                    ],
                )

                # Extract the text from Gemini's response
                if response.candidates and response.candidates[0].content.parts:
                    return response.candidates[0].content.parts[0].text.strip()

                return ""

            except Exception as e:
                # Retry on rate limits with exponential backoff + jitter
                if _is_rate_limit_error(e) and attempt < _MAX_RETRIES:
                    delay = _BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Rate limited on transcription (attempt {attempt + 1}/{_MAX_RETRIES}), "
                        f"retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Error transcribing audio: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return ""



    # ------------------------------------------------------------------
    # Core agent interaction
    # ------------------------------------------------------------------

    async def _collect_agent_response(
        self, user_id: str, session_id: str, user_content: types.Content
    ) -> str:
        """Collect streamed agent response parts into a single string."""
        response_parts = []
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            if hasattr(event, "content") and event.content:
                if hasattr(event.content, "parts"):
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            response_parts.append(part.text)
        return "".join(response_parts)

    async def _get_agent_response(self, user_id: str, message: str) -> str:
        """Send a message to the ADK agent with pre-verification gate.

        This is the central method that ALL handlers funnel through.  It:
          1. Checks verification cache (or Firestore on cache miss).
          2. If verified: prepends club context so the agent skips check_is_owner.
          3. If not verified: forwards to agent for onboarding flow.
             The agent will ask for email/code and link the account as needed.
          4. After agent responds for unverified users, checks if they just
             completed linking and caches them for future messages.

        Args:
            user_id: Telegram user ID.
            message: The text to send to the agent.

        Returns:
            The agent's complete response as a single string.
        """
        session_id = f"telegram_{user_id}"
        start_time = time.monotonic()
        verified = False

        # Circuit breaker: fail fast if the agent is repeatedly erroring.
        if time.time() < self._circuit_open_until:
            return "Service temporarily unavailable. Please try again shortly."

        async with self._agent_semaphore:
            try:
                # --- PRE-VERIFICATION GATE ---
                verification = await self._check_verification(user_id)

                if verification:
                    verified = True
                    # Verified user: inject context so agent skips check_is_owner
                    augmented_message = self._prepend_verification_context(message, verification)
                else:
                    # Unverified user: forward as-is for onboarding flow
                    augmented_message = message

                # --- SESSION ---
                session = await self.session_service.get_session(
                    app_name="mybola_agent",
                    user_id=user_id,
                    session_id=session_id,
                )

                if session is None:
                    session = await self.session_service.create_session(
                        app_name="mybola_agent",
                        user_id=user_id,
                        session_id=session_id,
                    )
                    logger.info(f"Created new session for user {user_id}")

                # --- AGENT CALL ---
                user_content = types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=augmented_message)],
                )

                for attempt in range(_MAX_RETRIES + 1):
                    try:
                        response_text = await asyncio.wait_for(
                            self._collect_agent_response(
                                user_id=user_id,
                                session_id=session_id,
                                user_content=user_content,
                            ),
                            timeout=_AGENT_TIMEOUT_SECONDS,
                        )

                        # If the user was unverified, check if they just completed
                        # linking so we can cache them for future messages.
                        if not verification:
                            await self._try_cache_after_linking(user_id)

                        if not response_text:
                            response_text = "I received your message but couldn't generate a response."

                        # Reset circuit breaker on success.
                        self._agent_failures = 0
                        return response_text

                    except Exception as e:
                        if _is_rate_limit_error(e) and attempt < _MAX_RETRIES:
                            delay = _BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                            logger.warning(
                                f"Rate limited on agent response (attempt {attempt + 1}/{_MAX_RETRIES}), "
                                f"retrying in {delay:.1f}s"
                            )
                            await asyncio.sleep(delay)
                        else:
                            raise

            except Exception as e:
                self._agent_failures += 1
                if self._agent_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                    self._circuit_open_until = time.time() + _CIRCUIT_BREAKER_TIMEOUT

                logger.error(f"Error getting agent response: {e}")
                import traceback
                logger.error(traceback.format_exc())
                if isinstance(e, asyncio.TimeoutError):
                    AGENT_ERRORS.labels(type="timeout").inc()
                    return "The service took too long to respond. Please try again."
                if _is_rate_limit_error(e):
                    AGENT_ERRORS.labels(type="rate_limit").inc()
                    return "The service is currently busy. Please try again in a moment."
                AGENT_ERRORS.labels(type="other").inc()
                return f"Error processing your request: {str(e)}"
            finally:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                AGENT_LATENCY.labels(verified="true" if verified else "false").observe(
                    elapsed_ms / 1000
                )
                logger.info(
                    f"Agent response time for {user_id} "
                    f"({'verified' if verified else 'unverified'}): {elapsed_ms:.0f}ms"
                )

    # ------------------------------------------------------------------
    # Webhook entry point (called by main.py's FastAPI route)
    # ------------------------------------------------------------------

    async def handle_webhook(self, update_data: dict):
        """Handle an incoming webhook POST from Telegram.

        This is the top-level entry point.  Cloud Run receives a POST request
        from Telegram, main.py extracts the JSON body, and passes it here.

        The python-telegram-bot library deserializes the raw dict into an
        Update object and dispatches it to the correct handler based on the
        registered CommandHandlers / MessageHandlers.

        Args:
            update_data: Raw JSON dict from Telegram's webhook POST body.
        """
        try:
            # Deserialize the raw dict → python-telegram-bot Update object
            update = Update.de_json(update_data, self.app.bot)
            # Dispatch to the matching handler (command_menu, handle_message, etc.)
            await self.app.process_update(update)
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}")
            raise
