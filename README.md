# MyBola Club Manager (Telegram Bot)

A Cloud Run deployed Telegram bot that helps football club owners manage members, sessions, billing, and merchandise. It uses Gemini (via Vertex AI), FastAPI, and Firestore for persistent sessions.

**Key pieces**
- FastAPI app + Telegram webhook endpoint
- ADK agent with domain tools in `mybola_agent/`
- Firestore-backed session service

**Repo layout**
```
app/
  __init__.py
  main.py                     # FastAPI entry point + webhook
  telegram_handler.py         # Telegram bot handler + ADK runner
  services/
    __init__.py
    firestore_session_service.py
mybola_agent/
  agent.py                    # Root agent + instructions
  tools/                      # Domain tools

docs/
  telegram_setup.md

requirements.txt
.env.example
```

**Environment variables**
- `GOOGLE_CLOUD_PROJECT` (required)
- `GOOGLE_CLOUD_LOCATION` (required)
- `GOOGLE_GENAI_USE_VERTEXAI=True` (required)
- `TELEGRAM_BOT_TOKEN` (required for Telegram)
- `GMAIL_USER`, `GMAIL_APP_PASSWORD` (optional)
- `APP_ENV` (optional, default `production`)
- `LOG_LEVEL` (optional, default `INFO`)
- `AGENT_CONCURRENCY` (optional, default `10`)
- `AGENT_TIMEOUT_SECONDS` (optional, default `45`)
- `PORT` (optional, default 8080)

**Local dev**
```bash
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

**Deploy to Cloud Run**
```bash
gcloud run deploy mybola-admin \
  --source . \
  --region asia-southeast1 \
  --project YOUR_PROJECT_ID \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID" \
  --set-env-vars "GOOGLE_CLOUD_LOCATION=us-central1" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=True" \
  --set-env-vars "TELEGRAM_BOT_TOKEN=your-bot-token" \
  --set-env-vars "GMAIL_USER=you@gmail.com" \
  --set-env-vars "GMAIL_APP_PASSWORD=your-app-password" \
  --memory 4Gi \
  --cpu 2 \
  --timeout 120 \
  --min-instances 0 \
  --max-instances 5 \
  --cpu-throttling \
  --allow-unauthenticated
```

**Telegram setup**
See `docs/telegram_setup.md`.

**Operational docs**
- `docs/runbook.md`
- `docs/security.md`
- `docs/data_retention.md`
- `docs/incident_response.md`
- `docs/load_testing.md`
