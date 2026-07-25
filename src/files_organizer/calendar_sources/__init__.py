from ..models import Event
from .base import CalendarSource
from .ics_source import IcsCalendarSource

__all__ = ["CalendarSource", "IcsCalendarSource", "get_calendar_source", "filter_events_by_tag"]


def filter_events_by_tag(events: list[Event], include_tags: list[str] | None) -> list[Event]:
    """Keep only events whose tag is in `include_tags`.

    `include_tags` is an allowlist rather than a blocklist: calendars mix real
    events with reminders/tasks that carry no useful tag, so listing the tags
    that *do* represent photo-worthy events is more robust than trying to name
    every kind of noise to exclude. `None` (not configured) keeps everything.
    """
    if include_tags is None:
        return events
    return [event for event in events if event.tag in include_tags]


def get_calendar_source(config: dict) -> CalendarSource:
    source_type = config["type"]

    if source_type == "ics":
        return IcsCalendarSource(path=config["path"])
    if source_type == "google":
        from .google_source import GoogleCalendarSource

        return GoogleCalendarSource(**{k: v for k, v in config.items() if k != "type"})
    if source_type == "outlook":
        from .outlook_source import OutlookCalendarSource

        return OutlookCalendarSource(**{k: v for k, v in config.items() if k != "type"})

    raise ValueError(f"Unknown calendar source type: {source_type}")
