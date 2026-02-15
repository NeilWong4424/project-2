# Firestore Schema (Code + Observed)

Firestore is schemaless. This document combines:
1) Collections and fields inferred from the codebase, and
2) Fields observed in the Firestore console screenshots you provided.

Observed data date: 2026-02-11.

## Collections (Observed in Console)
- `adk_sessions`
- `billing`
- `club`
- `ff_user_push_notifications`
- `matches`
- `member`
- `point_change`
- `product`
- `sesi`
- `shirt`
- `standingchanges`
- `standings`
- `stats`
- `subscription`
- `teams`
- `users`

Only the collections below are documented in detail so far (based on code and the screenshots).

## Collections Used by MyBola Agent Code
- `club`
- `users`
- `member`
- `sesi`
- `billing`
- `shirt_orders`
- `adk_sessions` (ADK session storage; sub-collections)

## Collection: `club`

Fields in code (referenced):
- `name` (string)
- `address` (string)
- `contact` (string)

Fields observed in Firestore:
- `admin` (array of string)
- `lastPayment` (timestamp)
- `name` (string)
- `notice4` (string)
- `phone_number` (string)
- `plan` (string)
- `premium` (boolean)
- `reg` (string)

## Collection: `users`

Fields in code (referenced):
- `email` (string)
- `name` (string, optional)
- `club_owner` (boolean)
- `club_admin` (boolean)
- `club_ref` (string or DocumentReference)
- `telegram_id` (string)
- `telegram_linked_at` (timestamp)
- `verification_code` (string)
- `verification_requested_at` (timestamp)

Fields observed in Firestore:
- Not captured in screenshots yet.

## Collection: `member`

Fields in code (referenced):
- `club_ref` (string)
- `name` (string)
- `ic_number` (string)
- `phone` (string)
- `parent_name` (string)
- `parent_phone` (string)
- `email` (string or null)
- `status` (string)
- `joined_at` (timestamp)

Fields observed in Firestore:
- `club_ref` (string or DocumentReference)
- `dob` (timestamp)
- `name` (string)
- `nota` (string)
- `tag` (array of string)
- `telephone` (string)

## Collection: `sesi` (training sessions)

Fields in code (referenced):
- `club_ref` (string)
- `title` (string)
- `date` (string, YYYY-MM-DD)
- `time` (string, HH:MM)
- `location` (string)
- `description` (string)
- `created_at` (timestamp)
- `status` (string)

Fields observed in Firestore:
- `ageGroup` (string)
- `clubRef` (string or DocumentReference)
- `createdAt` (timestamp)
- `date` (timestamp)
- `duration` (number)
- `location` (string)
- `name` (string)
- `price` (number)

## Collection: `billing`

Fields in code (referenced):
- `club_ref` (string)
- `member_id` (string)
- `member_name` (string)
- `amount` (number)
- `description` (string)
- `due_date` (string, YYYY-MM-DD)
- `status` (string)
- `created_at` (timestamp)
- `updated_at` (timestamp)

Fields observed in Firestore:
- `amount` (number)
- `club_ref` (string or DocumentReference)
- `date` (timestamp)
- `description` (string)
- `invoice` (string)
- `member` (string)
- `member_ref` (string or DocumentReference)
- `premium` (boolean)
- `status` (string)
- `user_ref` (string or DocumentReference)

## Collection: `shirt` vs `shirt_orders`

Fields in code (referenced, collection name `shirt_orders`):
- `club_ref` (string)
- `member_id` (string)
- `size` (string)
- `quantity` (number)
- `color` (string)
- `status` (string)
- `ordered_at` (timestamp)

Fields observed in Firestore (collection name `shirt`):
- `club_ref` (string or DocumentReference)
- `count` (number)
- `img` (array of string, URLs)
- `live` (boolean)
- `name` (string)
- `price` (number)
- `variant` (map; keys not visible in screenshot)

## Collection: `adk_sessions`

This is managed by `FirestoreSessionService` with a collection prefix `adk`.
The layout is:

```
adk_sessions/{app_name}/users/{user_id}/sessions/{session_id}
adk_sessions/{app_name}/users/{user_id}/sessions/{session_id}/events/{event_id}
```

Session document fields:
- `app_name` (string)
- `user_id` (string)
- `id` (string)
- `state` (map)
- `create_time` (timestamp)
- `update_time` (timestamp)

Event document fields:
- `id` (string)
- `app_name` (string)
- `user_id` (string)
- `session_id` (string)
- `invocation_id` (string)
- `author` (string)
- `timestamp` (timestamp)
- `content` (map or null)
- `actions` (map or null)
- `branch` (string or null)
- `long_running_tool_ids` (array or null)
- `partial` (boolean)
- `turn_complete` (boolean)
- `error_code` (string or null)
- `error_message` (string or null)
- `interrupted` (boolean)

## Notes on Code Alignment
- Code now treats `shirt` as the canonical collection and accepts `shirt_orders` as a legacy alias.
- `sesi` uses `clubRef` in Firestore; code writes/queries `clubRef` and falls back to `club_ref` for legacy docs.
- Member and billing tools map legacy field names when provided (e.g., `phone` → `telephone`, `ic_number` → `nota`).
