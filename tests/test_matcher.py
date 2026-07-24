from datetime import datetime
from pathlib import Path

from files_organizer.matcher import MatchStatus, match_photo_to_event
from files_organizer.models import Event, Photo


def make_event(start: str, end: str, name: str = "Wakacje", tag: str | None = None) -> Event:
    return Event(name=name, start=datetime.fromisoformat(start), end=datetime.fromisoformat(end), tag=tag)


def make_photo(taken_at: str) -> Photo:
    return Photo(path=Path("photo.jpg"), taken_at=datetime.fromisoformat(taken_at))


def test_matches_photo_within_event_range():
    event = make_event("2026-07-15T10:00:00", "2026-07-15T18:00:00")
    photo = make_photo("2026-07-15T12:00:00")

    result = match_photo_to_event(photo, [event])

    assert result.status == MatchStatus.MATCHED
    assert result.event == event


def test_matches_photo_within_margin():
    event = make_event("2026-07-15T10:00:00", "2026-07-15T18:00:00")
    photo = make_photo("2026-07-15T19:30:00")

    result = match_photo_to_event(photo, [event], margin_hours=2)

    assert result.status == MatchStatus.MATCHED


def test_unmatched_when_outside_margin():
    event = make_event("2026-07-15T10:00:00", "2026-07-15T18:00:00")
    photo = make_photo("2026-07-15T22:00:00")

    result = match_photo_to_event(photo, [event], margin_hours=2)

    assert result.status == MatchStatus.UNMATCHED
    assert result.event is None


def test_overlapping_events_reported():
    event_a = make_event("2026-07-15T10:00:00", "2026-07-15T18:00:00", name="Impreza A")
    event_b = make_event("2026-07-15T12:00:00", "2026-07-15T20:00:00", name="Impreza B")
    photo = make_photo("2026-07-15T13:00:00")

    result = match_photo_to_event(photo, [event_a, event_b])

    assert result.status == MatchStatus.OVERLAPPING


def test_unmatched_when_photo_has_no_timestamp():
    photo = Photo(path=Path("photo.jpg"), taken_at=None)

    result = match_photo_to_event(photo, [])

    assert result.status == MatchStatus.UNMATCHED
