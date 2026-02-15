# Runbook

## Deploy
Use the README deploy command or CI/CD pipeline.

## Verify Service Health
- `GET /healthz` for basic readiness.
- `GET /telegram/webhook-status` for Telegram bot status.
- `GET /metrics` for Prometheus metrics.

## Common Issues
### Bot not responding
- Check logs for errors in Cloud Run.
- Verify `TELEGRAM_BOT_TOKEN` is set.
- Confirm Telegram webhook points to the correct service URL.

### Agent timeouts
- Increase `AGENT_TIMEOUT_SECONDS` if timeouts are frequent.
- Check Vertex AI quota and rate limits.

### Firestore permission errors
- Verify Cloud Run service account has Firestore access.
- Confirm `GOOGLE_CLOUD_PROJECT` and database settings.

## Rollback
Use Cloud Run to roll back to the previous revision if needed.
