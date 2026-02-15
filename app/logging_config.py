import logging
import os

from pythonjsonlogger import jsonlogger


def setup_logging() -> None:
    """Configure structured JSON logging for Cloud Run."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [handler]
