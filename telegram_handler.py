"""Telegram bot webhook handler for ADK agent integration."""
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Handler for Telegram bot webhook integration with ADK agent."""

    def __init__(self, bot_token: str, agent_session_service):
        """Initialize Telegram bot handler.

        Args:
            bot_token: Telegram bot token
            agent_session_service: ADK session service for agent interactions
        """
        self.bot_token = bot_token
        self.agent_session_service = agent_session_service
        self.app = None

    async def initialize(self):
        """Initialize Telegram application."""
        self.app = Application.builder().token(self.bot_token).build()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
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
            f"👋 Welcome {user_name}! I'm your AI assistant.\n\n"
            "Use /help to see available commands or just send me a message!"
        )

        logger.info(f"Telegram user started: {user_id}")

    async def help_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """
Available commands:
/start - Start the conversation
/help - Show this help message
/new - Start a new conversation session

Just send any message and I'll respond!
        """
        await update.message.reply_text(help_text)

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

            # Send response back to Telegram
            # Note: In a real implementation, you'd interact with the ADK agent here
            # For now, we send a placeholder response
            response_text = f"Received your message: {user_message}"

            # Split long messages
            if len(response_text) > 4096:
                for chunk in [response_text[i : i + 4096] for i in range(0, len(response_text), 4096)]:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response_text)

        except Exception as e:
            logger.error(f"Error processing Telegram message: {e}")
            await update.message.reply_text(
                "Sorry, I encountered an error processing your message. Please try again."
            )

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
