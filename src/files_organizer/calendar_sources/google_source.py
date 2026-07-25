from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..models import Event
from .base import CalendarSource

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]

_HASHTAG_RE = re.compile(r"#(\w+)")


class GoogleCalendarSource(CalendarSource):
    """Reads events via the Google Calendar API.

    Requires an OAuth `credentials_file` (Desktop app client secret from
    Google Cloud Console). On first run a browser window opens for consent
    and a `token.json` is cached next to it for subsequent runs.

    Both paths support `~` for the home directory, so the credentials and
    token can be kept outside the project directory, e.g.
    `~/.config/files-organizer/token.json`.
    """

    def __init__(self, credentials_file: str, calendar_id: str = "primary", token_file: str = "token.json"):
        self.credentials_file = Path(credentials_file).expanduser()
        self.calendar_id = calendar_id
        self.token_file = Path(token_file).expanduser()

    def get_events(self) -> list[Event]:
        service = self._build_service()
        response = (
            service.events()
            .list(calendarId=self.calendar_id, singleEvents=True, orderBy="startTime")
            .execute()
        )
        return [_to_event(item) for item in response.get("items", [])]

    def _build_service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        try:
            creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        except FileNotFoundError:
            pass

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json())

        return build("calendar", "v3", credentials=creds)


def _to_event(item: dict) -> Event:
    return Event(
        name=item.get("summary", ""),
        start=_parse_datetime(item["start"]),
        end=_parse_datetime(item["end"]),
        location=item.get("location"),
        tag=_extract_tag(item),
    )


def _extract_tag(item: dict) -> str | None:
    """Tag comes from a `#tag` hashtag in the title or description.

    `extendedProperties` (the "proper" place for metadata) isn't settable
    from the Google Calendar UI, only via the API, so it's useless for a
    human tagging their own events. A hashtag is something anyone can type
    in the title while creating an event.
    """
    for text in (item.get("summary", ""), item.get("description", "")):
        match = _HASHTAG_RE.search(text)
        if match:
            return match.group(1)
    return None


def _parse_datetime(value: dict) -> datetime:
    parsed = datetime.fromisoformat(value.get("dateTime", value.get("date")))
    return parsed.replace(tzinfo=None)
