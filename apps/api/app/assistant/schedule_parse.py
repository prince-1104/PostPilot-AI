"""Resolve natural-language schedule phrases into offset-aware datetimes."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class ScheduleParseResult:
    proposed_scheduled_at: datetime | None
    ambiguous: bool
    reason: str | None = None


_TIME_RE = re.compile(
    r"\b(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?\b",
    re.IGNORECASE,
)
_MONTHS = {name.lower(): idx for idx, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): idx for idx, name in enumerate(calendar.month_abbr) if name})


def parse_schedule_expression(
    text: str | None,
    *,
    timezone_name: str | None,
    now: datetime | None = None,
) -> ScheduleParseResult:
    if not text or not text.strip():
        return ScheduleParseResult(None, ambiguous=False)

    if not timezone_name:
        return ScheduleParseResult(
            None,
            ambiguous=True,
            reason="Select an IANA timezone so local times are not treated as UTC.",
        )
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ScheduleParseResult(
            None, ambiguous=True, reason=f"Unknown timezone: {timezone_name}"
        )

    clock = now.astimezone(zone) if now else datetime.now(zone)
    lower = text.lower()
    time_match = _TIME_RE.search(text)
    hour, minute = _resolve_clock(time_match)

    if "tomorrow" in lower:
        target = (clock + timedelta(days=1)).replace(
            hour=hour if hour is not None else 9,
            minute=minute if minute is not None else 0,
            second=0,
            microsecond=0,
        )
        if hour is None:
            return ScheduleParseResult(
                None, ambiguous=True, reason="What time tomorrow should we use?"
            )
        return ScheduleParseResult(target, ambiguous=False)

    if "today" in lower:
        if hour is None:
            return ScheduleParseResult(
                None, ambiguous=True, reason="What time today should we use?"
            )
        target = clock.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)
        if target <= clock:
            return ScheduleParseResult(
                None,
                ambiguous=True,
                reason="That time today appears to be in the past. Pick a future time.",
            )
        return ScheduleParseResult(target, ambiguous=False)

    weekday = _next_weekday(lower, clock)
    if weekday is not None:
        if hour is None:
            return ScheduleParseResult(
                None, ambiguous=True, reason="What time on that weekday should we use?"
            )
        target = weekday.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)
        return ScheduleParseResult(target, ambiguous=False)

    month_day = _parse_month_day(lower, clock)
    if month_day is not None:
        if hour is None:
            return ScheduleParseResult(
                None, ambiguous=True, reason="What time on that date should we use?"
            )
        target = month_day.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)
        return ScheduleParseResult(target, ambiguous=False)

    # Bare "7 PM" without a date is ambiguous.
    if hour is not None:
        return ScheduleParseResult(
            None,
            ambiguous=True,
            reason="Which date should we use for that time?",
        )

    return ScheduleParseResult(
        None,
        ambiguous=True,
        reason="Could not interpret a concrete date/time from the schedule text.",
    )


def _resolve_clock(match: re.Match[str] | None) -> tuple[int | None, int | None]:
    if match is None:
        return None, None
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower().replace(".", "")
    if ampm.startswith("p") and hour < 12:
        hour += 12
    if ampm.startswith("a") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None, None
    return hour, minute


def _next_weekday(lower: str, clock: datetime) -> datetime | None:
    for i, full in enumerate(calendar.day_name):
        tokens = {full.lower(), calendar.day_abbr[i].lower()}
        matched = any(
            f"next {token}" in lower or re.search(rf"\b{re.escape(token)}\b", lower)
            for token in tokens
        )
        if not matched:
            continue
        days_ahead = (i - clock.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (clock + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return None


def _parse_month_day(lower: str, clock: datetime) -> datetime | None:
    match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|"
        r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"\s+(\d{1,2})\b",
        lower,
    )
    if not match:
        return None
    month = _MONTHS.get(match.group(1))
    day = int(match.group(2))
    if month is None or day < 1 or day > 31:
        return None
    year = clock.year
    try:
        candidate = datetime(year, month, day, tzinfo=clock.tzinfo)
    except ValueError:
        return None
    if candidate.date() < clock.date():
        try:
            candidate = datetime(year + 1, month, day, tzinfo=clock.tzinfo)
        except ValueError:
            return None
    return candidate


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
