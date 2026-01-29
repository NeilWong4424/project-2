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

### Webhook Not Receiving Messages

1. Check webhook status:
```bash
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
```

2. Verify the URL is correct and publicly accessible:
```bash
curl https://adk-agent-service-xxxxx.run.app/telegram/webhook-status
```

3. Check Cloud Run logs:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agent-service" \
    --project=loop-470211 \
    --limit=50
```

### "Telegram bot not configured"

- Ensure `TELEGRAM_BOT_TOKEN` environment variable is set
- Redeploy after setting the token
- Restart the application: `gcloud run services update-traffic adk-agent-service --to-revisions LATEST`

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

- Each Telegram user gets a unique session identified by their Telegram user ID
- Conversation history is stored in Firestore under:
  ```
  adk_sessions/my_agent/users/{telegram_user_id}/sessions/telegram_{user_id}
  ```
- Sessions persist across messages and bot restarts

### Message Handling

The `TelegramBotHandler` class:
- Receives messages via webhook (webhook handler)
- Routes messages through the ADK agent
- Manages Telegram-specific commands (`/start`, `/help`, `/new`)
- Handles typing indicators and long messages (Telegram 4096 char limit)
- Logs all interactions for debugging

### Architecture

```
Telegram User
    ↓
Telegram Bot API (webhook)
    ↓
POST /webhook/telegram (main.py)
    ↓
TelegramBotHandler.handle_webhook()
    ↓
ADK Agent (my_agent/agent.py)
    ↓
Firestore Session Storage
    ↓
Response back to Telegram
```

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
