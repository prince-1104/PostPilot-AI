"""IANA timezone validation and DST/offset consistency checks."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import AppError


class InvalidTimezoneError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_CONTENT
    code = "invalid_timezone"


class TimezoneConsistencyError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_CONTENT
    code = "timezone_inconsistent"


def require_iana_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise InvalidTimezoneError(
            f"Unknown IANA timezone {name!r}. Use a value such as 'UTC' or 'Asia/Kolkata'."
        ) from exc
    except Exception as exc:  # ZoneInfo can raise other errors for malformed keys
        raise InvalidTimezoneError(f"Invalid IANA timezone {name!r}.") from exc


def assert_offset_matches_timezone(scheduled_at: datetime, timezone_name: str) -> None:
    """Ensure the client's offset matches the IANA zone at the scheduled instant.

    ``scheduled_at`` must already be timezone-aware. At that UTC instant, the offset
    of ``timezone_name`` must equal ``scheduled_at.utcoffset()``. This rejects naive
    assumptions and catches DST mismatches where the wall-clock offset is wrong.
    """
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        raise TimezoneConsistencyError("scheduled_at must include a UTC offset.")

    tz = require_iana_timezone(timezone_name)
    expected_offset = scheduled_at.astimezone(tz).utcoffset()
    actual_offset = scheduled_at.utcoffset()
    if expected_offset != actual_offset:
        raise TimezoneConsistencyError(
            f"The offset on scheduled_at does not match {timezone_name} at that instant. "
            "Send an offset-aware timestamp consistent with the selected IANA timezone."
        )
