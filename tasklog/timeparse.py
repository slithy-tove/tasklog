"""Parsing of date and time strings.

Times (used by `ID manual START END`):
  17:00:00               today at 17:00:00 (also accepts 17:00)
  2026-10-17::17:00:00   an explicit date and time
  today::17:00:00        today's date with the given time
  yesterday::17:00:00    yesterday's date with the given time
  now                    the current moment

Days (used by `report -d` and `report -dr`):
  2026-10-17, today, yesterday, now
  Anything after "::" is ignored, so "today::17:00:00" also works.

All times are naive local times, matching the machine's clock.
"""
import re
from datetime import datetime, time, timedelta

from .errors import TasklogError

SEP = "::"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _date_from_word(text: str, today):
    word = text.strip().lower()
    if word in ("today", "now"):
        return today
    if word == "yesterday":
        return today - timedelta(days=1)
    if _ISO_DATE.fullmatch(word):
        try:
            return datetime.strptime(word, "%Y-%m-%d").date()
        except ValueError:
            pass  # e.g. 2026-13-45; fall through to the error below
    raise TasklogError(f"unrecognized date '{text}' (use YYYY-MM-DD, today, or yesterday)")


def _time_from_text(text: str) -> time:
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text.strip(), fmt).time()
        except ValueError:
            continue
    raise TasklogError(f"unrecognized time '{text}' (use HH:MM:SS, e.g. 17:00:00)")


def parse_datetime(text: str, now: datetime = None) -> datetime:
    """Parse a date-and-time string into a datetime. See the module docstring for forms."""
    now = now or datetime.now().replace(microsecond=0)
    s = text.strip().lower()

    if s == "now":
        return now
    if SEP in s:
        date_part, time_part = s.split(SEP, 1)
        return datetime.combine(_date_from_word(date_part, now.date()), _time_from_text(time_part))
    if _ISO_DATE.fullmatch(s) or s in ("today", "yesterday"):
        return datetime.combine(_date_from_word(s, now.date()), time(0))
    # Bare time of day: assume today.
    return datetime.combine(now.date(), _time_from_text(s))


def parse_day(text: str, now: datetime = None):
    """Parse a day for report filters. Returns a date object."""
    now = now or datetime.now()
    return _date_from_word(text.strip().split(SEP, 1)[0], now.date())
