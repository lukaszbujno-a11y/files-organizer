from __future__ import annotations

from datetime import datetime

from ..models import Event
from .base import CalendarSource


class OutlookCalendarSource(CalendarSource):
    """Reads events via Microsoft Graph (Outlook/Microsoft 365 calendar).

    Requires an app registration in Azure AD with `Calendars.Read`
    delegated permission. On first run a device-flow login prompt is shown
    and the token is cached in `token_file` for subsequent runs.
    """

    def __init__(self, client_id: str, client_secret: str | None = None, token_file: str = "o365_token.txt"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file

    def get_events(self) -> list[Event]:
        from O365 import Account, FileSystemTokenBackend

        backend = FileSystemTokenBackend(token_filename=self.token_file)
        credentials = (self.client_id, self.client_secret) if self.client_secret else (self.client_id,)
        account = Account(credentials, token_backend=backend)
        if not account.is_authenticated:
            account.authenticate(scopes=["basic", "calendar_all"])

        schedule = account.schedule()
        calendar = schedule.get_default_calendar()
        return [_to_event(item) for item in calendar.get_events(include_recurring=True)]


def _to_event(item) -> Event:
    return Event(
        name=item.subject or "",
        start=_to_naive(item.start),
        end=_to_naive(item.end),
        location=item.location.get("displayName") if item.location else None,
        tag=item.categories[0] if item.categories else None,
    )


def _to_naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
