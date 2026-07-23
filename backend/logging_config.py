"""Structured logging with credential redaction.

A single ``configure_logging()`` sets up the root logger, and a ``RedactionFilter``
scrubs anything that looks like a password out of every log record — so a stray
connection string or DB URL in a log message can never leak secrets to stdout,
files, or a log aggregator.
"""

import logging
import re

# Matches the password in a SQLAlchemy/DB URL:  scheme://user:PASSWORD@host
_URL_CRED = re.compile(r"(://[^:/@\s]+:)([^@/\s]+)(@)")
# Matches an explicit MCP_DB_URL=... assignment appearing in a message
_ENV_URL = re.compile(r"(MCP_DB_URL=)(\S+)")


def redact(text: str) -> str:
    """Replace passwords in connection strings / DB URLs with ``***``."""
    text = _URL_CRED.sub(r"\1***\3", text)
    text = _ENV_URL.sub(r"\1***", text)
    return text


class RedactionFilter(logging.Filter):
    """Redact secrets from the formatted message and any string args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")
    )
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
