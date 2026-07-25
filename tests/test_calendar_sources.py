from datetime import datetime

from files_organizer.calendar_sources import filter_events_by_tag
from files_organizer.models import Event


def make_event(name: str, tag: str | None) -> Event:
    return Event(name=name, start=datetime(2026, 7, 15, 10, 0), end=datetime(2026, 7, 15, 18, 0), tag=tag)


def test_no_include_tags_keeps_all_events():
    events = [make_event("Wakacje", "Wakacje"), make_event("Przypomnienie", None)]

    assert filter_events_by_tag(events, None) == events


def test_include_tags_keeps_only_matching_events():
    wakacje = make_event("Wakacje", "Wakacje")
    reminder = make_event("Przypomnienie", "Przypomnienie")
    untagged = make_event("Bez tagu", None)

    result = filter_events_by_tag([wakacje, reminder, untagged], ["Wakacje"])

    assert result == [wakacje]


def test_include_tags_drops_untagged_events():
    untagged = make_event("Bez tagu", None)

    assert filter_events_by_tag([untagged], ["Wakacje"]) == []
