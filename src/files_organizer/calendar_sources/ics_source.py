from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from icalendar import Calendar

from ..models import Event
from .base import CalendarSource


class IcsCalendarSource(CalendarSource):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get_events(self) -> list[Event]:
        content = self.path.read_bytes()
        calendar = Calendar.from_ical(content)

        events = []
        for component in calendar.walk("VEVENT"):
            start = _to_datetime(component.decoded("dtstart"))
            end = _to_datetime(component.decoded("dtend"))
            categories = component.get("categories")
            tag = categories.cats[0] if categories and categories.cats else None

            events.append(
                Event(
                    name=str(component.get("summary", "")),
                    start=start,
                    end=end,
                    location=str(component.get("location")) if component.get("location") else None,
                    tag=str(tag) if tag else None,
                )
            )
        return events


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.combine(value, time.min)
