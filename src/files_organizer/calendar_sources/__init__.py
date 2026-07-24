from .base import CalendarSource
from .ics_source import IcsCalendarSource

__all__ = ["CalendarSource", "IcsCalendarSource"]


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
