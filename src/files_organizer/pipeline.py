from __future__ import annotations

import threading
import time
from collections import Counter
from pathlib import Path
from typing import Callable

from .calendar_sources import filter_events_by_tag, get_calendar_source
from .config import Config
from .exif_reader import iter_media_files, read_photo_metadata
from .location_recognizers import get_location_recognizer
from .matcher import MatchStatus
from .organizer import build_target_dir, place_photo
from .rules import classify_photos

LogFn = Callable[[str], None]


def run_pipeline(config: Config, dry_run: bool, log: LogFn, stop_event: threading.Event | None = None) -> None:
    """Classify every media file under config.input_dir (see `rules.classify_photos`) and file it away.

    Shared between the CLI loop and the GUI's background worker thread; `log` receives
    one line per processed file so both can render it (terminal echo / GUI log widget).

    `stop_event`, if given, is checked *between* files only, never mid-copy/move — so a
    requested stop always leaves the file system in a consistent state (every file that
    was started is finished; nothing is left half-copied). The caller is responsible for
    reporting whether the run ended early (`stop_event.is_set()` after this returns).

    Runs in two passes, because the date rule can only count a day's photos once every file
    has been read: first all metadata is read (nothing touches the file system yet, so
    stopping there is always safe), then every file is copied/moved.
    """
    started = time.monotonic()
    stopped = lambda: stop_event is not None and stop_event.is_set()
    mode = "podgląd (dry-run)" if dry_run else ("kopiowanie" if config.mode == "copy" else "przenoszenie")
    log(f"Start: {config.input_dir} -> {config.output_dir} | tryb: {mode} | reguły: {' → '.join(config.rules) or 'brak'}")

    events = []
    if "calendar" in config.rules:
        if config.calendar:
            phase_started = time.monotonic()
            log(f"[1/3] Kalendarz: pobieram wydarzenia ({config.calendar.get('type', '?')})…")
            calendar_source = get_calendar_source(config.calendar)
            events = filter_events_by_tag(calendar_source.get_events(), config.include_tags)
            log(f"[1/3] Kalendarz: {len(events)} wydarzeń ({_elapsed(phase_started)})")
        else:
            log("[1/3] Kalendarz: brak sekcji 'calendar' w konfiguracji - reguła nic nie przypisze")
    else:
        log("[1/3] Kalendarz: reguła wyłączona")

    location_recognizer = None
    if "location" in config.rules:
        location_recognizer = get_location_recognizer(config.location_recognition or {})

    phase_started = time.monotonic()
    paths = list(iter_media_files(config.input_dir))
    log(f"[2/3] Analiza: odczyt metadanych {len(paths)} plików…")
    photos = []
    last_progress = time.monotonic()
    for index, path in enumerate(paths, start=1):
        if stopped():
            return
        photos.append(read_photo_metadata(path))
        if index % 50 == 0 or time.monotonic() - last_progress >= 2:
            log(f"  metadane: {index}/{len(paths)} ({_elapsed(phase_started)})")
            last_progress = time.monotonic()
    log(f"[2/3] Analiza: metadane odczytane ({_elapsed(phase_started)})")

    if location_recognizer is not None:
        log(f"[2/3] Analiza: rozpoznawanie lokalizacji ({(config.location_recognition or {}).get('type', 'reverse_geocoder')})…")
    classified = classify_photos(photos, config, events, location_recognizer, log=log, should_stop=stopped)
    if stopped():
        return

    by_status = Counter(match.status for _, match in classified)
    summary = ", ".join(f"{_STATUS_LABELS[status]}: {by_status[status]}" for status in _STATUS_LABELS if by_status[status])
    log(f"[2/3] Analiza zakończona ({_elapsed(phase_started)}) - {summary or 'brak plików'}")

    phase_started = time.monotonic()
    to_place = len(classified) - by_status[MatchStatus.UNMATCHED]
    log(f"[3/3] {'Podgląd' if dry_run else mode.capitalize()}: {to_place} plików, {by_status[MatchStatus.UNMATCHED]} pominiętych…")
    for index, (photo, match) in enumerate(classified, start=1):
        if stopped():
            return

        taken_at = f"{photo.taken_at:%Y-%m-%d %H:%M}" if photo.taken_at else "brak daty"
        prefix = f"[{index}/{len(classified)}] {_relative(photo.path, config.input_dir)} ({taken_at})"
        label = _STATUS_LABELS[match.status]
        reason = f": {match.detail}" if match.detail else ""

        if match.status == MatchStatus.UNMATCHED:
            log(f"{prefix} -> pominięto ({match.detail})")
        elif dry_run:
            log(f"{prefix} -> {_relative(build_target_dir(config, photo, match), config.output_dir)} [{label}{reason}]")
        else:
            destination = place_photo(config, photo, match)
            log(f"{prefix} -> {_relative(destination, config.output_dir)} [{label}{reason}]")

    log(f"[3/3] Zakończono ({_elapsed(phase_started)}); łącznie {_elapsed(started)}")


_STATUS_LABELS = {
    MatchStatus.MATCHED: "kalendarz",
    MatchStatus.OVERLAPPING: "kalendarz - nakładające się wydarzenia",
    MatchStatus.LOCATION: "lokalizacja",
    MatchStatus.DATE_GROUP: "data",
    MatchStatus.UNMATCHED: "pominięte",
}


def _elapsed(since: float) -> str:
    seconds = time.monotonic() - since
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes} min {seconds} s"


def _relative(path: Path, base: Path | None) -> str:
    """`path` relative to `base` when it's inside it - full paths make every log line unreadably long."""
    try:
        return str(path.relative_to(base)) if base is not None else str(path)
    except ValueError:
        return str(path)
