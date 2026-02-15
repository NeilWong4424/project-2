# Data Retention

## Stored Data
- Firestore sessions (conversation context)
- Account linking metadata (email/telegram ID mapping)

## Recommended Policy
- Retain sessions for 90 days unless business requirements dictate otherwise.
- Provide a manual deletion process for user requests.

## Deletion Process
- Identify user by Telegram ID and remove related session documents.
- Ensure backups follow the same retention policy.
