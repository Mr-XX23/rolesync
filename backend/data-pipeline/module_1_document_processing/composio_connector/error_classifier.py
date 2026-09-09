import re
from enum import Enum
from typing import Any

class ConnectorErrorType(str, Enum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    ITEM_CORRUPT = "ITEM_CORRUPT"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    UNKNOWN = "UNKNOWN"

class ConnectorAction(str, Enum):
    RECONNECT = "RECONNECT"
    RETRY_WITH_BACKOFF = "RETRY_WITH_BACKOFF"
    SKIP_ITEM = "SKIP_ITEM"
    ABORT_JOB = "ABORT_JOB"
    NO_ACTION = "NO_ACTION"

_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
    re.compile(r"ak_[A-Za-z0-9_\-]+", re.IGNORECASE),
    re.compile(r"secret_[A-Za-z0-9_\-]+", re.IGNORECASE),
    re.compile(r"xox[baprs]-[A-Za-z0-9_\-]+", re.IGNORECASE),
    re.compile(r"client_secret=[^\s&]+", re.IGNORECASE),
    re.compile(r"access_token=[^\s&]+", re.IGNORECASE),
    re.compile(r"refresh_token=[^\s&]+", re.IGNORECASE),
]

def sanitize_error_message(msg: str) -> str:
    """Removes API keys, OAuth tokens, and sensitive headers from error messages."""
    if not msg:
        return ""
    sanitized = str(msg)
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_CREDENTIAL]", sanitized)
    return sanitized

def classify_error(err: Any) -> tuple[ConnectorErrorType, str, ConnectorAction]:
    """
    Classifies raw connector exceptions into clean taxonomy with suggested recovery action.
    Returns: (ConnectorErrorType, sanitized_user_message, ConnectorAction)
    """
    raw_str = str(err).lower()
    sanitized = sanitize_error_message(str(err))

    # 1. OAuth / Auth Expiration
    auth_signatures = (
        "invalid_grant",
        "invalid_token",
        "token expired",
        "token has expired",
        "unauthorized",
        "401",
        "authentication failed",
        "token_revoked",
        "oauth_signature_invalid",
        "credentials expired",
    )
    if any(sig in raw_str for sig in auth_signatures):
        return (
            ConnectorErrorType.AUTH_EXPIRED,
            "OAuth token expired or was revoked. Please reconnect your account to continue syncing.",
            ConnectorAction.RECONNECT,
        )

    # 2. Rate Limits
    if "429" in raw_str or "rate limit" in raw_str or "rate_limited" in raw_str or "quota exceeded" in raw_str:
        return (
            ConnectorErrorType.RATE_LIMITED,
            "Provider API rate limit reached. Synchronization will pause and resume automatically.",
            ConnectorAction.RETRY_WITH_BACKOFF,
        )

    # 3. File Too Large
    if "413" in raw_str or "too large" in raw_str or "exceeds maximum" in raw_str or "size limit" in raw_str:
        return (
            ConnectorErrorType.FILE_TOO_LARGE,
            "Item exceeds configured size limit and was skipped.",
            ConnectorAction.SKIP_ITEM,
        )

    # 4. Resource Not Found / Deleted Upstream
    if "404" in raw_str or "not found" in raw_str or "deleted" in raw_str or "no longer exists" in raw_str:
        return (
            ConnectorErrorType.RESOURCE_NOT_FOUND,
            "Item was deleted or not found on the upstream provider.",
            ConnectorAction.SKIP_ITEM,
        )

    # 5. Transient Network Errors
    transient_signatures = (
        "500", "502", "503", "504", "gateway timeout",
        "connection reset", "econnreset", "timed out", "timeout",
    )
    if any(sig in raw_str for sig in transient_signatures):
        return (
            ConnectorErrorType.TRANSIENT_NETWORK,
            "Temporary network connectivity issue. Auto-retrying...",
            ConnectorAction.RETRY_WITH_BACKOFF,
        )

    # 6. Payload / Encoding Corrupt
    if "unicodedecodeerror" in raw_str or "jsondecodeerror" in raw_str or "unparseable" in raw_str:
        return (
            ConnectorErrorType.ITEM_CORRUPT,
            "Item content could not be decoded or parsed; item skipped.",
            ConnectorAction.SKIP_ITEM,
        )

    return (
        ConnectorErrorType.UNKNOWN,
        sanitized[:250],
        ConnectorAction.ABORT_JOB,
    )
