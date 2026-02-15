"""Constants and configuration values for MyBola agent."""

# Firestore Collection Names
COLLECTION_USERS = "users"
COLLECTION_CLUBS = "club"
COLLECTION_MEMBERS = "member"
COLLECTION_SESSIONS = "sesi"
COLLECTION_BILLING = "billing"
COLLECTION_SHIRTS = "shirt"

# ADK Collections
COLLECTION_ADK_SESSIONS = "adk_sessions"
COLLECTION_ADK_APP_STATES = "adk_app_states"
COLLECTION_ADK_USER_STATES = "adk_user_states"

# App Configuration
APP_NAME = "mybola_agent"
DEFAULT_DATABASE = "(default)"
ADK_COLLECTION_PREFIX = "adk"

# Bill Statuses
BILL_STATUS_TERTUNGGAK = "Tertunggak"  # Overdue/Unpaid
BILL_STATUS_DIBAYAR = "Dibayar"  # Paid
BILL_STATUS_BATAL = "Batal"  # Cancelled
BILL_STATUS_SEBAHAGIAN = "Sebahagian"  # Partially paid

ALLOWED_BILL_STATUSES = [
    BILL_STATUS_TERTUNGGAK,
    BILL_STATUS_DIBAYAR,
    BILL_STATUS_BATAL,
    BILL_STATUS_SEBAHAGIAN
]

# Member Statuses
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_INACTIVE = "inactive"
MEMBER_STATUS_SUSPENDED = "suspended"

ALLOWED_MEMBER_STATUSES = [
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_INACTIVE,
    MEMBER_STATUS_SUSPENDED
]

# Session Statuses
SESSION_STATUS_SCHEDULED = "scheduled"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUS_CANCELLED = "cancelled"

ALLOWED_SESSION_STATUSES = [
    SESSION_STATUS_SCHEDULED,
    SESSION_STATUS_COMPLETED,
    SESSION_STATUS_CANCELLED
]

# Shirt Order Statuses
SHIRT_STATUS_ORDERED = "ordered"
SHIRT_STATUS_RECEIVED = "received"
SHIRT_STATUS_DELIVERED = "delivered"
SHIRT_STATUS_CANCELLED = "cancelled"

ALLOWED_SHIRT_STATUSES = [
    SHIRT_STATUS_ORDERED,
    SHIRT_STATUS_RECEIVED,
    SHIRT_STATUS_DELIVERED,
    SHIRT_STATUS_CANCELLED
]

# Limits
MAX_QUERY_LIMIT = 100
DEFAULT_QUERY_LIMIT = 50
MAX_BATCH_SIZE = 400  # Firestore batch limit is 500, use 400 for safety

# Validation Limits
MAX_TEXT_LENGTH = 500
MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254  # RFC 5321
MAX_PHONE_LENGTH = 20
MIN_AMOUNT = 0.01
MAX_AMOUNT = 999999.99

# Date Formats
DATE_FORMAT_YYYY_MM_DD = "%Y-%m-%d"
DATETIME_FORMAT_ISO = "%Y-%m-%dT%H:%M:%S"

# Telegram
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

# Rate Limiting
RATE_LIMIT_WEBHOOK = "30/minute"
RATE_LIMIT_RETRY_AFTER = 60  # seconds

# Model Configuration
DEFAULT_MODEL = "gemini-2.5-flash"

# Club-scoped collections readable via read_club_data
READABLE_COLLECTIONS = {
    COLLECTION_CLUBS,       # "club"
    COLLECTION_MEMBERS,     # "member"
    COLLECTION_SESSIONS,    # "sesi"
    COLLECTION_BILLING,     # "billing"
    COLLECTION_SHIRTS,      # "shirt"
}

# Aliases so the LLM can use human-friendly names
COLLECTION_ALIASES = {
    "clubs": COLLECTION_CLUBS,
    "club": COLLECTION_CLUBS,
    "members": COLLECTION_MEMBERS,
    "member": COLLECTION_MEMBERS,
    "sessions": COLLECTION_SESSIONS,
    "sesi": COLLECTION_SESSIONS,
    "billing": COLLECTION_BILLING,
    "bills": COLLECTION_BILLING,
    "shirt": COLLECTION_SHIRTS,
    "shirt_orders": COLLECTION_SHIRTS,  # legacy alias
    "shirts": COLLECTION_SHIRTS,
    "orders": COLLECTION_SHIRTS,
}

# Allowed Firestore filter operators for read_club_data
ALLOWED_FILTER_OPS = {"==", "!=", "<", "<=", ">", ">=", "in", "not-in", "array-contains"}
