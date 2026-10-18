from __future__ import annotations

import time
from collections import Counter
from typing import Callable

from .config import Config
from .location_recognizers import GeocoderUnavailableError, LocationRecognizer
from .matcher import MatchResult, MatchStatus, match_photo_to_event
from .models import Event, Photo

LogFn = Callable[[str], None]

_SOURCE_LABELS = {"offline": "offline", "cache": "cache", "api": "API", "no_gps": "brak GPS"}


def classify_photos(
    photos: list[Photo],
    config: Config,
    events: list[Event],
    location_recognizer: LocationRecognizer | None = None,
    log: LogFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    numbering: tuple[int, int] | None = None,
    location_stats: Counter[str] | None = None,
) -> list[tuple[Photo, MatchResult]]:
    """Decide where each photo goes by trying `config.rules` in order; the first rule that
    places a photo wins, and a photo no rule places comes back UNMATCHED, with `detail` saying
    why each rule passed on it.

    - `calendar`: the photo falls within a calendar event (MATCHED, or OVERLAPPING when several do).
    - `location`: the photo's EXIF GPS resolves to a place outside `config.home_country`
      (any recognized place when `home_country` is unset).
    - `date`: more than `config.date_group_threshold` photos from the same day reached this rule.

    The date rule needs to see the whole batch before it can decide anything, so it's resolved
    in a second pass: the first pass only marks which photos reached it, while still working out
    what the rules after it would do for them, in case their day turns out too small.

    `log`, when given, gets a line per location lookup (the slow, possibly online step) and a
    summary of where the location names came from.

    `should_stop`, when given, is checked between photos; once it returns True the photos not
    yet looked at are left out of the result (the caller is expected to stop anyway).

    For calling this one photo at a time (possible whenever `date` isn't among the rules):
    `numbering` = `(index, total)` numbers the log lines within the whole run instead of within
    `photos`, and a caller-owned `location_stats` collects the lookup sources across calls -
    the summary line is then left to the caller.
    """
    log = log or (lambda message: None)
    summarize = location_stats is None
    location_stats = Counter() if location_stats is None else location_stats
    location_started = time.monotonic()
    start_index, total = numbering or (1, len(photos))

    first_pass = []
    for index, photo in enumerate(photos, start=start_index):
        if should_stop is not None and should_stop():
            break
        reached_date = False
        result = None
        reasons = []
        for rule in config.rules:
            if rule == "date":
                reached_date = photo.taken_at is not None
                if not reached_date:
                    reasons.append("data: brak daty zdjęcia")
                continue
            result, reason, origin = _apply_rule(rule, photo, config, events, location_recognizer, location_stats)
            if origin:
                # only photos that actually needed a lookup - "no GPS" is just counted in the summary
                log(f"  [{index}/{total}] {photo.path.name}: {reason or f'lokalizacja: {result.detail}'} [{origin}]")
            if result is not None:
                break
            reasons.append(reason)
        first_pass.append((photo, reached_date, result, reasons))

    if summarize and location_stats:
        log(f"  Lokalizacje ustalone w {time.monotonic() - location_started:.1f} s ({describe_location_stats(location_stats)})")

    per_day = Counter(photo.taken_at.date() for photo, reached_date, _, _ in first_pass if reached_date)
    results = []
    for photo, reached_date, result, reasons in first_pass:
        if reached_date:
            count = per_day[photo.taken_at.date()]
            if count > config.date_group_threshold:
                results.append((photo, MatchResult(status=MatchStatus.DATE_GROUP, detail=f"{count} zdjęć z dnia")))
                continue
            # keep the reasons in rule order: this one belongs where `date` sits in config.rules
            position = list(config.rules).index("date")
            reasons.insert(min(position, len(reasons)), f"data: {count} zdjęć z dnia, potrzeba > {config.date_group_threshold}")
        if result is None:
            result = MatchResult(status=MatchStatus.UNMATCHED, detail="; ".join(reasons) or "brak włączonych reguł")
        results.append((photo, result))
    return results


def describe_location_stats(location_stats: Counter[str]) -> str:
    """E.g. "API: 2, cache: 5, brak GPS: 3"."""
    return ", ".join(f"{_SOURCE_LABELS.get(source, source)}: {count}" for source, count in sorted(location_stats.items()))


def _apply_rule(
    rule: str,
    photo: Photo,
    config: Config,
    events: list[Event],
    location_recognizer: LocationRecognizer | None,
    location_stats: Counter[str],
) -> tuple[MatchResult | None, str, str]:
    """Return `(result, reason, origin)` - the result when the rule places the photo, otherwise
    None and a short reason it didn't; `origin` says where a location lookup got its answer
    ("API, 1.1 s"), empty when no lookup happened."""
    if rule == "calendar":
        match = match_photo_to_event(photo, events, margin_hours=config.margin_hours)
        if match.status == MatchStatus.UNMATCHED:
            return None, "kalendarz: brak daty zdjęcia" if photo.taken_at is None else "kalendarz: brak wydarzenia", ""
        return match, "", ""

    if rule == "location":
        if location_recognizer is None:
            return None, "lokalizacja: wyłączona", ""
        # the folder name starts with the date, so a photo without one can't be placed here
        if photo.taken_at is None:
            return None, "lokalizacja: brak daty zdjęcia", ""
        try:
            location = location_recognizer.recognize(photo.path)
        except (ImportError, GeocoderUnavailableError):
            raise
        except Exception as exc:
            return None, f"lokalizacja: błąd rozpoznawania ({exc})", "błąd"

        source = location_recognizer.last_source
        if source is None and location is None:
            location_stats["no_gps"] += 1
            return None, "lokalizacja: brak GPS", ""
        origin = ""
        if source is not None:
            location_stats[source] += 1
            detail = location_recognizer.last_source_detail
            origin = f"{_SOURCE_LABELS.get(source, source)}{', ' + detail if detail else ''}"
        if location is None:
            return None, "lokalizacja: nie rozpoznano miejsca", origin
        place = f"{location.city}, {location.country}"
        if config.home_country and location.country.casefold() == config.home_country.casefold():
            return None, f"lokalizacja: {place} - kraj domowy", origin
        return MatchResult(status=MatchStatus.LOCATION, location=location, detail=place), "", origin

    raise ValueError(f"Unknown rule: {rule!r}")
