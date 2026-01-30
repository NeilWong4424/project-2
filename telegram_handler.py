"""Telegram bot webhook handler for ADK agent integration."""
import logging
import tempfile
import os

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

logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Handler for Telegram bot webhook integration with ADK agent."""

    def __init__(self, bot_token: str, agent, session_service):
        """Initialize Telegram bot handler.

        Args:
            bot_token: Telegram bot token
            agent: ADK agent instance
            session_service: ADK session service for agent interactions
        """
        self.bot_token = bot_token
        self.agent = agent
        self.session_service = session_service
        self.app = None
        self.runner = None

    async def initialize(self):
        """Initialize Telegram application."""
        self.app = Application.builder().token(self.bot_token).build()

        # Initialize ADK runner if agent and session service are provided
        if self.agent and self.session_service:
            self.runner = Runner(
                agent=self.agent,
                app_name="my_agent",
                session_service=self.session_service,
            )
            logger.info("ADK Runner initialized for Telegram")

        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("new", self.new_session_command))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        # Add audio/voice message handler
        self.app.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self.handle_audio_message)
        )

        await self.app.initialize()

    async def shutdown(self):
        """Shutdown Telegram application."""
        if self.app:
            await self.app.stop()

    async def start_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.first_name or "User"

        await update.message.reply_text(
            f"Welcome {user_name}! I'm your AI assistant powered by Gemini.\n\n"
            "Just send me a message and I'll help you!\n"
            "Use /new to start a fresh conversation."
        )

        logger.info(f"Telegram user started: {user_id}")

    async def help_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """Available commands:
/start - Start the conversation
/help - Show this help message
/new - Start a new conversation session

You can interact with me by:
- Sending text messages
- Sending voice messages (I'll transcribe and respond)
- Sending audio files (I'll transcribe and respond)

Just send any message and I'll respond with AI!"""
        await update.message.reply_text(help_text)

    async def new_session_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE):
        """Handle /new command to start a new session."""
        user_id = str(update.effective_user.id)

        # Create a new session by using a new session ID
        if self.session_service:
            session_id = f"telegram_{user_id}_{int(update.message.date.timestamp())}"
            await update.message.reply_text(
                "New conversation started! Your previous chat history has been cleared."
            )
            logger.info(f"New session created for user {user_id}: {session_id}")
        else:
            await update.message.reply_text("Session management not available.")

    async def handle_message(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle incoming messages from Telegram users."""
        user_id = str(update.effective_user.id)
        user_message = update.message.text

        try:
            # Show typing indicator
            await update.message.chat.send_action("typing")

            logger.info(
                f"Processing Telegram message from {user_id}: {user_message[:50]}"
            )

            # Get response from ADK agent
            if self.runner and self.session_service:
                response_text = await self._get_agent_response(user_id, user_message)
            else:
                response_text = f"Agent not configured. Your message: {user_message}"

            # Split long messages (Telegram limit is 4096 chars)
            if len(response_text) > 4096:
                for chunk in [response_text[i : i + 4096] for i in range(0, len(response_text), 4096)]:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response_text)

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
        """Handle incoming voice/audio messages from Telegram users."""
        user_id = str(update.effective_user.id)

        try:
            # Show typing indicator
            await update.message.chat.send_action("typing")

            # Get the audio file (voice message or audio file)
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

            # Download the audio file
            file = await self.app.bot.get_file(audio_file.file_id)

            # Download to a temporary file
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
                tmp_path = tmp_file.name
                await file.download_to_drive(tmp_path)

            try:
                # Transcribe audio using Gemini
                transcribed_text = await self._transcribe_audio(tmp_path)

                if not transcribed_text:
                    await update.message.reply_text(
                        "I couldn't understand the audio. Please try again or send a text message."
                    )
                    return

                logger.info(f"Transcribed audio: {transcribed_text[:100]}...")

                # Notify user what was transcribed
                await update.message.reply_text(f"🎤 I heard: \"{transcribed_text}\"")

                # Show typing indicator again for agent response
                await update.message.chat.send_action("typing")

                # Get response from ADK agent
                if self.runner and self.session_service:
                    response_text = await self._get_agent_response(user_id, transcribed_text)
                else:
                    response_text = f"Agent not configured. Your message: {transcribed_text}"

                # Split long messages (Telegram limit is 4096 chars)
                if len(response_text) > 4096:
                    for chunk in [response_text[i : i + 4096] for i in range(0, len(response_text), 4096)]:
                        await update.message.reply_text(chunk)
                else:
                    await update.message.reply_text(response_text)

            finally:
                # Clean up temp file
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
        """Transcribe audio file using Gemini.

        Args:
            audio_path: Path to the audio file

        Returns:
            Transcribed text
        """
        try:
            # Initialize Gemini client for Vertex AI
            client = genai.Client(vertexai=True)

            # Read the audio file as bytes (Vertex AI doesn't support files.upload)
            with open(audio_path, "rb") as f:
                audio_data = f.read()

            # Use Gemini to transcribe with inline audio data
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(
                                data=audio_data,
                                mime_type="audio/ogg",
                            ),
                            types.Part.from_text(
                                text="Please transcribe this audio message accurately. "
                                "Return only the transcription, nothing else. "
                                "If the audio is unclear or empty, return an empty string."
                            ),
                        ],
                    )
                ],
            )

            # Extract text from response
            if response.candidates and response.candidates[0].content.parts:
                transcribed_text = response.candidates[0].content.parts[0].text.strip()
                return transcribed_text

            return ""

        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ""

    async def _get_agent_response(self, user_id: str, message: str) -> str:
        """Get response from ADK agent.

        Args:
            user_id: Telegram user ID
            message: User's message

        Returns:
            Agent's response text
        """
        session_id = f"telegram_{user_id}"

        try:
            # Get or create session
            session = await self.session_service.get_session(
                app_name="my_agent",
                user_id=user_id,
                session_id=session_id,
            )

            if session is None:
                session = await self.session_service.create_session(
                    app_name="my_agent",
                    user_id=user_id,
                    session_id=session_id,
                )
                logger.info(f"Created new session for user {user_id}")

            # Create user message content
            user_content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            )

            # Run agent and collect response
            response_parts = []
            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_content,
            ):
                # Collect text from agent response events
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts'):
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                response_parts.append(part.text)

            response_text = "".join(response_parts)

            if not response_text:
                response_text = "I received your message but couldn't generate a response."

            return response_text

        except Exception as e:
            logger.error(f"Error getting agent response: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"Error processing your request: {str(e)}"

    async def handle_webhook(self, update_data: dict):
        """Handle incoming webhook update from Telegram.

        Args:
            update_data: Raw update data from Telegram webhook
        """
        try:
            update = Update.de_json(update_data, self.app.bot)
            await self.app.process_update(update)
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}")
            raise
