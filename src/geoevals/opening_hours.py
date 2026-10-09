"""Pure-Python evaluation of a subset of OpenStreetMap ``opening_hours`` values.

No network access and no third-party packages: the parser is a few regular expressions, and the
time zone check uses the standard library's ``zoneinfo`` (with the ``tzdata`` package as the
fallback time zone database).

Supported subset (the rest of the OSM grammar raises ``OpeningHoursError``):

- ``24/7``: always open;
- rules separated by ``;``, each ``[<selector> ](<spans>|off|closed)``;
- a selector is a comma-separated list of weekdays (``Mo`` .. ``Su``), weekday ranges
  (``Mo-Fr``; a range may wrap, as ``Fr-Mo``) and ``PH`` (public holiday). A rule without a
  selector applies to every day;
- spans are comma-separated ``HH:MM-HH:MM``, start before ``24:00``, end up to ``24:00``. An end
  earlier than the start crosses midnight. A span with equal start and end is rejected.

Semantics, as defined in ``docs/human-context.md``:

- For each date, the rule that applies is the **last** rule whose selector matches it. ``PH``
  matches a date only when the date is in the case's list of public holidays; weekday
  selectors match holidays too, so ``Mo-Su 08:00-22:00; PH off`` is closed on a listed holiday.
- A span is open from its start (inclusive) to its end (exclusive).
- A span that crosses midnight belongs to the day on which it starts: ``Fr 22:00-02:00`` is open
  on Saturday at 01:00 even when a later rule closes Saturday.

``open_state`` is the entry point for data: it returns ``None`` (unknown) for a missing or
unparseable value, so callers report it as missing data rather than fail.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
"""OSM weekday abbreviations, Monday first (``date.weekday()`` order)."""

MINUTES_PER_DAY = 24 * 60

_TIME = r"(?:[01]\d|2[0-4]):[0-5]\d"
_SPAN = re.compile(rf"({_TIME})-({_TIME})")
_RULE = re.compile(
    rf"(?:(?P<selector>[A-Za-z,\-]+)\s+)?(?P<hours>off|closed|{_TIME}-{_TIME}(?:,{_TIME}-{_TIME})*)"
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class OpeningHoursError(ValueError):
    """An ``opening_hours`` value outside the supported subset."""


@dataclass(frozen=True)
class Rule:
    weekdays: frozenset[int]
    """``date.weekday()`` values the rule applies to."""
    public_holiday: bool
    """The rule applies to listed public holidays."""
    spans: tuple[tuple[int, int], ...]
    """``(start, end)`` in minutes after the start of the day; ``end`` > 1440 crosses midnight.
    Empty: closed."""

    def matches(self, day: date, holidays: frozenset[date]) -> bool:
        return day.weekday() in self.weekdays or (self.public_holiday and day in holidays)


@dataclass(frozen=True)
class OpeningHours:
    rules: tuple[Rule, ...]

    def rule_for(self, day: date, holidays: frozenset[date]) -> Rule | None:
        """The last rule that matches ``day``, or ``None`` (closed)."""
        found = None
        for rule in self.rules:
            if rule.matches(day, holidays):
                found = rule
        return found

    def is_open(self, when: datetime, holidays: frozenset[date] = frozenset()) -> bool:
        """Whether the place is open at the local wall-clock time ``when``."""
        day, minute = when.date(), when.hour * 60 + when.minute
        today = self.rule_for(day, holidays)
        if today and any(start <= minute < end for start, end in today.spans):
            return True
        yesterday = self.rule_for(day - timedelta(days=1), holidays)
        return bool(yesterday and any(minute < end - MINUTES_PER_DAY for _, end in yesterday.spans))


def _minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _selector(text: str) -> tuple[frozenset[int], bool]:
    weekdays: set[int] = set()
    public_holiday = False
    for part in text.split(","):
        if part == "PH":
            public_holiday = True
            continue
        first, _, last = part.partition("-")
        if first not in WEEKDAYS or (last and last not in WEEKDAYS):
            raise OpeningHoursError(f"unsupported day selector {part!r}")
        start = WEEKDAYS.index(first)
        end = WEEKDAYS.index(last) if last else start
        weekdays.update((start + k) % 7 for k in range((end - start) % 7 + 1))
    return frozenset(weekdays), public_holiday


def _spans(text: str) -> tuple[tuple[int, int], ...]:
    if text in ("off", "closed"):
        return ()
    spans = []
    for match in _SPAN.finditer(text):
        start, end = _minutes(match[1]), _minutes(match[2])
        if start >= MINUTES_PER_DAY or end > MINUTES_PER_DAY or start == end:
            raise OpeningHoursError(f"unsupported time span {match[0]!r}")
        spans.append((start, end if end > start else end + MINUTES_PER_DAY))
    return tuple(spans)


def parse(value: str) -> OpeningHours:
    """Parse an ``opening_hours`` value; raises ``OpeningHoursError`` outside the subset."""
    text = value.strip()
    if text == "24/7":
        return OpeningHours((Rule(frozenset(range(7)), True, ((0, MINUTES_PER_DAY),)),))
    rules = []
    for part in text.split(";"):
        match = _RULE.fullmatch(part.strip())
        if match is None:
            raise OpeningHoursError(f"unsupported rule {part.strip()!r}")
        if match["selector"] is None:
            weekdays, public_holiday = frozenset(range(7)), False
        else:
            weekdays, public_holiday = _selector(match["selector"])
        rules.append(Rule(weekdays, public_holiday, _spans(match["hours"])))
    return OpeningHours(tuple(rules))


def open_state(
    value: str | None, when: datetime, holidays: frozenset[date] = frozenset()
) -> bool | None:
    """``True`` open, ``False`` closed, ``None`` unknown (no value, or one that cannot be
    parsed)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse(value).is_open(when, holidays)
    except OpeningHoursError:
        return None


def local_instant(day: Any, clock: Any, timezone: Any) -> datetime:
    """The aware local datetime of an ISO date ``YYYY-MM-DD``, a ``HH:MM`` time and an IANA
    time zone; raises ``ValueError`` when any of them is malformed or unknown."""
    if not (isinstance(day, str) and _DATE.fullmatch(day)):
        raise ValueError(f"date must be YYYY-MM-DD, got {day!r}")
    if not (isinstance(clock, str) and _CLOCK.fullmatch(clock)):
        raise ValueError(f"time must be HH:MM, got {clock!r}")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise ValueError(f"unknown time zone {timezone!r}") from error
    hours, minutes = clock.split(":")
    return datetime.combine(date.fromisoformat(day), time(int(hours), int(minutes)), zone)


def holiday_dates(values: Any) -> frozenset[date]:
    """ISO dates -> ``date`` set; raises ``ValueError`` for a malformed date."""
    if not isinstance(values, list):
        raise ValueError("public_holidays must be a list of dates")
    days = set()
    for value in values:
        if not (isinstance(value, str) and _DATE.fullmatch(value)):
            raise ValueError(f"public holiday must be YYYY-MM-DD, got {value!r}")
        days.add(date.fromisoformat(value))
    return frozenset(days)
