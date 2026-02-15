# Telegram Bot Setup

This guide covers the minimal steps to connect the MyBola Club Manager service to Telegram.

**Prereqs**
- A Telegram bot token from @BotFather
- A deployed Cloud Run service URL
- Env vars set: `TELEGRAM_BOT_TOKEN`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI=True`

**1. Create a Telegram bot**
1. Open Telegram and chat with `@BotFather`
2. Run `/newbot` and follow the prompts
3. Save the bot token

**2. Deploy and get the service URL**
Use the deploy steps in `README.md`, then fetch the URL (service name must match your deploy, e.g. `mybola-admin`):
```bash
gcloud run services describe YOUR_SERVICE_NAME \
  --region asia-southeast1 \
  --project YOUR_PROJECT_ID \
  --format='value(status.url)'
```

**3. Set the Telegram webhook**
Replace `YOUR_BOT_TOKEN` and `YOUR_SERVICE_URL`:
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://<YOUR_SERVICE_URL>/webhook/telegram"
```

**4. Verify**
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```
Optional service check:
```bash
curl "https://<YOUR_SERVICE_URL>/telegram/webhook-status"
```

**Common issues**
- 503 on webhook: `TELEGRAM_BOT_TOKEN` missing or bot failed to init
- No messages: webhook URL is wrong or not public
- App fails to start: check Cloud Run logs for startup errors
