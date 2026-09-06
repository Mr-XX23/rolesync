import re
from datetime import datetime, timezone, time
import email.utils
from typing import Any

# Regex to detect date-only strings like 2026-09-04 or 2026/09/04
_DATE_ONLY_REGEX = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")

def normalize_to_utc(val: Any) -> datetime:
    """
    Universally normalizes any date/time representation into a timezone-aware UTC datetime.
    - Naive datetimes are assigned UTC.
    - Aware datetimes are converted to UTC.
    - Date-only strings (e.g. '2026-09-04') default time to 12:00:00 UTC.
    - RFC 2822 email headers (e.g. 'Fri, 4 Sep 2026 14:23:01 +0000') are parsed accurately.
    - Epoch timestamps (seconds or milliseconds) are converted to UTC.
    """
    if val is None:
        return datetime.now(timezone.utc)

    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)

    if isinstance(val, (int, float)):
        try:
            # Check for millisecond epoch vs second epoch
            if val > 1e11:
                return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return datetime.now(timezone.utc)

        # 1. Check for date-only formats: YYYY-MM-DD or YYYY/MM/DD
        date_match = _DATE_ONLY_REGEX.match(val_str)
        if date_match:
            try:
                y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                # Default time to 12:00:00 PM UTC as requested
                return datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc)
            except Exception:
                pass

        # 2. Try ISO-8601 parsing
        try:
            iso_clean = val_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # 3. Try RFC 2822 / RFC 822 email date header parsing (e.g. 'Fri, 04 Sep 2026 14:23:01 GMT')
        try:
            parsed_rfc = email.utils.parsedate_to_datetime(val_str)
            if parsed_rfc.tzinfo is None:
                return parsed_rfc.replace(tzinfo=timezone.utc)
            return parsed_rfc.astimezone(timezone.utc)
        except Exception:
            pass

        # 4. Try parsing float string (e.g. Slack epoch "1725450000.000100")
        try:
            float_ts = float(val_str)
            if float_ts > 1e11:
                return datetime.fromtimestamp(float_ts / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(float_ts, tz=timezone.utc)
        except Exception:
            pass

    return datetime.now(timezone.utc)

def ensure_iso_str(val: Any) -> str:
    """Returns standardized ISO-8601 string in UTC (e.g. '2026-09-04T12:00:00+00:00')."""
    return normalize_to_utc(val).isoformat()
