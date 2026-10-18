from __future__ import annotations

from collections import Counter
from typing import Callable

from .config import Config
from .location_recognizers import GeocoderUnavailableError, LocationRecognizer
from .matcher import MatchResult, MatchStatus, match_photo_to_event
from .models import Event, Photo

LogFn = Callable[[str], None]

_UNMATCHED = MatchResult(status=MatchStatus.UNMATCHED)


def classify_photos(
    photos: list[Photo],
    config: Config,
    events: list[Event],
    location_recognizer: LocationRecognizer | None = None,
    log: LogFn | None = None,
) -> list[tuple[Photo, MatchResult]]:
    """Decide where each photo goes by trying `config.rules` in order; the first rule that
    places a photo wins, and a photo no rule places comes back UNMATCHED.

    - `calendar`: the photo falls within a calendar event (MATCHED, or OVERLAPPING when several do).
    - `location`: the photo's EXIF GPS resolves to a place outside `config.home_country`
      (any recognized place when `home_country` is unset).
    - `date`: more than `config.date_group_threshold` photos from the same day reached this rule.

    The date rule needs to see the whole batch before it can decide anything, so it's resolved
    in a second pass: the first pass only marks which photos reached it, while still working out
    what the rules after it would do for them, in case their day turns out too small.
    """
    first_pass = []
    for photo in photos:
        reached_date = False
        result = None
        for rule in config.rules:
            if rule == "date":
                reached_date = photo.taken_at is not None
                continue
            result = _apply_rule(rule, photo, config, events, location_recognizer, log)
            if result is not None:
                break
        first_pass.append((photo, reached_date, result or _UNMATCHED))

    per_day = Counter(photo.taken_at.date() for photo, reached_date, _ in first_pass if reached_date)
    date_group = MatchResult(status=MatchStatus.DATE_GROUP)
    return [
        (photo, date_group if reached_date and per_day[photo.taken_at.date()] > config.date_group_threshold else fallback)
        for photo, reached_date, fallback in first_pass
    ]


def _apply_rule(
    rule: str,
    photo: Photo,
    config: Config,
    events: list[Event],
    location_recognizer: LocationRecognizer | None,
    log: LogFn | None,
) -> MatchResult | None:
    if rule == "calendar":
        match = match_photo_to_event(photo, events, margin_hours=config.margin_hours)
        return None if match.status == MatchStatus.UNMATCHED else match

    if rule == "location":
        # the folder name starts with the date, so a photo without one can't be placed here
        if location_recognizer is None or photo.taken_at is None:
            return None
        try:
            location = location_recognizer.recognize(photo.path)
        except (ImportError, GeocoderUnavailableError):
            raise
        except Exception as exc:
            if log is not None:
                log(f"{photo.path} -> błąd rozpoznawania lokalizacji: {exc}")
            return None
        if location is None:
            return None
        if config.home_country and location.country.casefold() == config.home_country.casefold():
            return None
        return MatchResult(status=MatchStatus.LOCATION, location=location)

    raise ValueError(f"Unknown rule: {rule!r}")
