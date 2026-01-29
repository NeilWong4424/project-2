# Telegram Bot Integration Guide

This guide explains how to set up and deploy your project-2 ADK agent with Telegram bot support.

## Quick Start

### 1. Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the prompts:
   - Enter bot name (e.g., "My ADK Agent")
   - Enter bot username (e.g., `my_adk_agent_bot` - must end with `_bot`)
4. **Save the bot token** (you'll need it for deployment)

Example token: `123456789:ABCDefGHIjKLmnoPQRStuvWXYz1234567890`

### 2. Configure Bot Settings (Optional but Recommended)

```bash
# Via BotFather in Telegram:
/setcommands

# Then provide these commands:
start - Start chatting with the bot
help - Show available commands
new - Start a new conversation session
```

## Deployment

### Local Development

#### Prerequisites
- Python 3.11+
- GCP credentials (for Firestore)
- Telegram bot token

#### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=asia-southeast1
export GOOGLE_GENAI_USE_VERTEXAI=True
export TELEGRAM_BOT_TOKEN=your-bot-token-here

# Run locally
python main.py
```

The app starts at `http://localhost:8080`

**Note:** For local development with webhooks, you need a publicly accessible HTTPS URL. Use ngrok:

```bash
# In another terminal
ngrok http 8080

# Set webhook (use the ngrok URL):
curl -X POST https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://<your-ngrok-url>.ngrok.io/webhook/telegram"}'
```

### Google Cloud Run Deployment

#### Step 1: Update Deployment Command

Use the same deployment command as before, but add the Telegram bot token:

```bash
gcloud run deploy adk-agent-service \
    --source . \
    --region asia-southeast1 \
    --project loop-470211 \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=loop-470211" \
    --set-env-vars "GOOGLE_CLOUD_LOCATION=asia-southeast1" \
    --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=True" \
    --set-env-vars "TELEGRAM_BOT_TOKEN=your-bot-token-here" \
    --memory 512Mi \
    --cpu 1 \
    --timeout 60 \
    --min-instances 0 \
    --max-instances 5 \
    --cpu-throttling \
    --allow-unauthenticated
```

Replace `your-bot-token-here` with your actual bot token.

#### Step 2: Get Your Service URL

After deployment, get the service URL:

```bash
gcloud run services describe adk-agent-service \
    --region asia-southeast1 \
    --project loop-470211 \
    --format='value(status.url)'
```

This will output something like: `https://adk-agent-service-975087229168.asia-southeast1.run.app`

#### Step 3: Set Telegram Webhook

Replace `YOUR_BOT_TOKEN` and `YOUR_SERVICE_URL` below:

```bash
curl -X POST https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://<YOUR_SERVICE_URL>/webhook/telegram"}'
```

Example:
```bash
curl -X POST https://api.telegram.org/bot123456789:ABCDefGHIjKLmnoPQRStuvWXYz1234567890/setWebhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://adk-agent-service-975087229168.asia-southeast1.run.app/webhook/telegram"}'
```

Expected response:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

#### Step 4: Verify Webhook Setup

```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
```

Should return:
```json
{
  "ok": true,
  "result": {
    "url": "https://adk-agent-service-975087229168.asia-southeast1.run.app/webhook/telegram",
    "has_custom_certificate": false,
    "pending_update_count": 0,
    "max_connections": 40,
    "allowed_updates": ["message", "edited_message", ...]
  }
}
```

## API Endpoints

### Telegram Webhook
```
POST /webhook/telegram
```
Receives incoming messages and updates from Telegram. Automatically configured via `setWebhook`.

### Telegram Status
```
GET /telegram/webhook-status
```
Returns current Telegram bot connection status.

Example response:
```json
{
  "status": "active",
  "bot_username": "my_adk_agent_bot",
  "bot_name": "My ADK Agent"
}
```

### Web Interface
```
GET /dev-ui
```
Interactive web interface for testing the agent (supports both web and Telegram interactions).

## Usage

### Via Telegram

1. Find your bot on Telegram (search by bot username or click the link from BotFather)
2. Start a conversation:
   - Send `/start` to initialize
   - Send `/help` to see available commands
   - Send any message to chat with the agent
   - Send `/new` to start a new conversation session

### Via Web UI

Visit `https://adk-agent-service-975087229168.asia-southeast1.run.app/dev-ui`

## Troubleshooting

### Bot Returns 503 Error or "Telegram bot not configured"

**Symptoms:** Webhook returns 503, bot status shows "disabled"

**Root Cause:** The Telegram bot handler uses lazy initialization - it initializes on the first webhook call or status check, not during app startup.

**Solution:**
1. The bot should auto-initialize on first use
2. Check initialization by calling: `curl https://your-service-url/telegram/webhook-status`
3. If still failing, check logs for initialization errors:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agent-service-2" \
       --project=loop-470211 \
       --limit=50 | grep -i "telegram"
   ```

**Common issues:**
- Missing `TELEGRAM_BOT_TOKEN` environment variable
- Invalid bot token format
- ADK agent import errors

### Webhook Not Receiving Messages

1. Check webhook status:
```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
```

2. Verify the URL is correct and publicly accessible:
```bash
curl https://adk-agent-service-xxxxx.run.app/telegram/webhook-status
```

3. Check Cloud Run logs for webhook processing:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agent-service-2" \
    --project=loop-470211 \
    --limit=50
```

### Bot Only Echoes Messages (Not Using AI)

**Symptoms:** Bot responds with "Received your message: ..." instead of AI responses

**Root Cause:** Bot handler not connected to ADK agent or session service

**Solution:** Ensure [main.py](main.py:54-78) passes `root_agent` and `telegram_session_service` to TelegramBotHandler:

```python
telegram_handler = TelegramBotHandler(
    bot_token=TELEGRAM_BOT_TOKEN,
    agent=root_agent,  # Must be passed
    session_service=telegram_session_service,  # Must be passed
)
```

Check logs for "Telegram bot initialized with ADK agent successfully"

### Webhook Updates Getting Stuck

This happens when the webhook URL is unreachable. Reset it:

```bash
# Remove webhook
curl -X POST https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook

# Wait 30 seconds, then set it again
sleep 30

curl -X POST https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://<YOUR_SERVICE_URL>/webhook/telegram"}'
```

### Bot Not Responding

1. Check if bot is connected: `GET /telegram/webhook-status`
2. Send a test message to the bot
3. Check logs for errors
4. Verify agent is working via web UI at `/dev-ui`

## Integration Details

### Session Management

- Each Telegram user gets a unique session: `session_id = f"telegram_{user_id}"`
- Conversation history stored in Firestore under:
  ```
  adk_sessions/my_agent/users/{telegram_user_id}/sessions/telegram_{user_id}
  ```
- Sessions persist across messages and bot restarts
- Uses same `FirestoreSessionService` as web UI
- `/new` command creates new session with timestamp suffix

### Message Handling Flow

1. **Webhook receives Telegram update** → `POST /webhook/telegram`
2. **Lazy initialization** → Bot handler initializes on first call if not already initialized
3. **Message processing** → `TelegramBotHandler.handle_message()`
4. **Agent query** → `_get_agent_response()` calls ADK Runner
5. **Session lookup** → Get or create session from Firestore
6. **AI processing** → Message sent to Gemini 2.5 Flash via ADK agent
7. **Response collection** → Stream response events, extract text parts
8. **Reply sent** → Response sent back to Telegram (split if >4096 chars)

### Architecture

```
Telegram User
    ↓
Telegram Bot API (webhook)
    ↓
POST /webhook/telegram (main.py:81-95)
    ↓
TelegramBotHandler.handle_webhook() (telegram_handler.py:206)
    ↓
TelegramBotHandler.handle_message() (telegram_handler.py:118)
    ↓
_get_agent_response() (telegram_handler.py:146)
    ↓
ADK Runner.run_async() with root_agent (Gemini 2.5 Flash)
    ↓
Firestore Session Storage (project2 database)
    ↓
Response streamed back → Telegram reply_text()
```

### Key Implementation Files

- **[main.py](main.py)** - FastAPI app, webhook endpoint, lazy initialization
- **[telegram_handler.py](telegram_handler.py)** - Bot logic, message routing to ADK agent
- **[my_agent/agent.py](my_agent/agent.py)** - Gemini 2.5 Flash agent definition
- **[firestore_session_service.py](firestore_session_service.py)** - Session persistence

## Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Yes (for Telegram) | Your bot token from BotFather | `` |
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID | `` |
| `GOOGLE_CLOUD_LOCATION` | Yes | GCP region | `` |
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes | Use Vertex AI for Gemini | `` |
| `PORT` | No | Server port (set by Cloud Run) | `8080` |

### Bot Commands

Currently supported commands in the bot:
- `/start` - Greet user and show welcome message
- `/help` - Show help text with available commands
- `/new` - Start a new conversation session (not yet fully implemented)

## Cost Optimization

The Telegram integration adds minimal cost:
- Webhook requests count as normal Cloud Run invocations
- Each message triggers one Firestore write operation
- No additional bandwidth charges

**Estimated additional cost:** $0.01-0.05/month for light usage

## Future Enhancements

- [ ] Integrate with ADK agent for full conversational capabilities
- [ ] Support for inline queries and button callbacks
- [ ] File/media upload support
- [ ] Conversation branching and rollback
- [ ] Rich message formatting (buttons, keyboards)
- [ ] Rate limiting per user
- [ ] Admin commands for bot management
- [ ] Multi-language support

## Support

For issues:
1. Check Telegram webhook status: `GET /telegram/webhook-status`
2. Review Cloud Run logs
3. Test agent via web UI: `/dev-ui`
4. Verify GCP configuration and Firestore access

---

**Last Updated:** 2026-01-29
