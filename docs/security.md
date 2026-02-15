# Security Guidelines

## Secrets
- Store `TELEGRAM_BOT_TOKEN`, `GMAIL_APP_PASSWORD`, and any API keys in a secret manager.
- Rotate secrets every 90 days or immediately after any suspected exposure.
- Avoid checking secrets into git; use `.env` only for local development.

## Service Accounts
- Use least-privilege service accounts for Cloud Run.
- Grant only required roles (Firestore access, logging, and Vertex AI as needed).

## Audit & Logging
- Keep structured logs enabled and ship them to a centralized logging system.
- Enable audit logging for Firestore and IAM changes.

## Environment Validation
- Ensure required environment variables are present in production.
- Fail fast if critical configuration is missing.
