from prometheus_client import Counter, Histogram

# High-level message counts by type.
MESSAGE_TOTAL = Counter(
    "telegram_messages_total",
    "Total number of Telegram messages processed",
    ["type"],
)

# Command usage counts by command name.
COMMAND_TOTAL = Counter(
    "telegram_commands_total",
    "Total number of Telegram commands processed",
    ["command"],
)

# Agent call latency in seconds (verified vs unverified).
AGENT_LATENCY = Histogram(
    "agent_response_latency_seconds",
    "Time spent waiting for the agent response",
    ["verified"],
)

# Agent errors (rate limit or other).
AGENT_ERRORS = Counter(
    "agent_response_errors_total",
    "Total number of agent response errors",
    ["type"],
)
