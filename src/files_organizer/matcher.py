from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, auto

from .models import Event, Photo


class MatchStatus(Enum):
    MATCHED = auto()
    UNMATCHED = auto()
    OVERLAPPING = auto()


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    event: Event | None = None


def match_photo_to_event(photo: Photo, events: list[Event], margin_hours: float = 2) -> MatchResult:
    if photo.taken_at is None:
        return MatchResult(status=MatchStatus.UNMATCHED)

    margin = timedelta(hours=margin_hours)
    candidates = [
        event for event in events if (event.start - margin) <= photo.taken_at <= (event.end + margin)
    ]

    if not candidates:
        return MatchResult(status=MatchStatus.UNMATCHED)
    if len(candidates) > 1:
        return MatchResult(status=MatchStatus.OVERLAPPING)
    return MatchResult(status=MatchStatus.MATCHED, event=candidates[0])
