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
from .rules import classify_photos, describe_location_stats

LogFn = Callable[[str], None]


def run_pipeline(config: Config, dry_run: bool, log: LogFn, stop_event: threading.Event | None = None) -> None:
    """Classify every media file under config.input_dir (see `rules.classify_photos`) and file it away.

    Shared between the CLI loop and the GUI's background worker thread; `log` receives
    one line per processed file so both can render it (terminal echo / GUI log widget).

    `stop_event`, if given, is checked *between* files only, never mid-copy/move — so a
    requested stop always leaves the file system in a consistent state (every file that
    was started is finished; nothing is left half-copied). The caller is responsible for
    reporting whether the run ended early (`stop_event.is_set()` after this returns).

    With the `date` rule enabled it runs in two passes, because that rule can only count a
    day's photos once every file has been read: first all metadata is read (nothing touches the
    file system yet, so stopping there is always safe), then every file is copied/moved. Without
    it every photo can be decided on its own, so each file is read, classified and placed right
    away - copying starts with the first file instead of after a scan of the whole directory.
    """
    started = time.monotonic()
    stopped = lambda: stop_event is not None and stop_event.is_set()
    mode = "podgląd (dry-run)" if dry_run else ("kopiowanie" if config.mode == "copy" else "przenoszenie")
    two_pass = "date" in config.rules
    phases = 3 if two_pass else 2
    log(f"Start: {config.input_dir} -> {config.output_dir} | tryb: {mode} | reguły: {' → '.join(config.rules) or 'brak'}")

    events = []
    if "calendar" in config.rules:
        if config.calendar:
            phase_started = time.monotonic()
            log(f"[1/{phases}] Kalendarz: pobieram wydarzenia ({config.calendar.get('type', '?')})…")
            calendar_source = get_calendar_source(config.calendar)
            events = filter_events_by_tag(calendar_source.get_events(), config.include_tags)
            log(f"[1/{phases}] Kalendarz: {len(events)} wydarzeń ({_elapsed(phase_started)})")
        else:
            log(f"[1/{phases}] Kalendarz: brak sekcji 'calendar' w konfiguracji - reguła nic nie przypisze")
    else:
        log(f"[1/{phases}] Kalendarz: reguła wyłączona")

    location_recognizer = None
    if "location" in config.rules:
        location_recognizer = get_location_recognizer(config.location_recognition or {})
        log(f"Lokalizacja: {(config.location_recognition or {}).get('type', 'reverse_geocoder')}")

    paths = list(iter_media_files(config.input_dir))
    if two_pass:
        _run_two_pass(config, dry_run, log, stopped, paths, events, location_recognizer, mode)
    else:
        _run_streaming(config, dry_run, log, stopped, paths, events, location_recognizer, mode)
    if not stopped():
        log(f"Zakończono; łącznie {_elapsed(started)}")


def _run_two_pass(config, dry_run, log, stopped, paths, events, location_recognizer, mode) -> None:
    phase_started = time.monotonic()
    log(f"[2/3] Analiza (reguła 'date' potrzebuje wszystkich zdjęć naraz): odczyt metadanych {len(paths)} plików…")
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

    classified = classify_photos(photos, config, events, location_recognizer, log=log, should_stop=stopped)
    if stopped():
        return
    by_status = Counter(match.status for _, match in classified)
    log(f"[2/3] Analiza zakończona ({_elapsed(phase_started)}) - {_describe_statuses(by_status)}")

    phase_started = time.monotonic()
    skipped = by_status[MatchStatus.UNMATCHED]
    log(f"[3/3] {'Podgląd' if dry_run else mode.capitalize()}: {len(classified) - skipped} plików, {skipped} pominiętych…")
    for index, (photo, match) in enumerate(classified, start=1):
        if stopped():
            return
        _place_and_log(config, dry_run, log, photo, match, index, len(classified))
    log(f"[3/3] {'Podgląd' if dry_run else mode.capitalize()} zakończone ({_elapsed(phase_started)})")


def _run_streaming(config, dry_run, log, stopped, paths, events, location_recognizer, mode) -> None:
    phase_started = time.monotonic()
    log(f"[2/2] {'Podgląd' if dry_run else mode.capitalize()}: {len(paths)} plików, każdy od razu po analizie…")
    by_status: Counter[MatchStatus] = Counter()
    location_stats: Counter[str] = Counter()
    for index, path in enumerate(paths, start=1):
        if stopped():
            return
        photo = read_photo_metadata(path)
        [(photo, match)] = classify_photos(
            [photo], config, events, location_recognizer, log=log, numbering=(index, len(paths)), location_stats=location_stats
        )
        by_status[match.status] += 1
        _place_and_log(config, dry_run, log, photo, match, index, len(paths))

    log(f"[2/2] {'Podgląd' if dry_run else mode.capitalize()} zakończone ({_elapsed(phase_started)}) - {_describe_statuses(by_status)}")
    if location_stats:
        log(f"  Lokalizacje: {describe_location_stats(location_stats)}")


def _place_and_log(config, dry_run, log, photo, match, index, total) -> None:
    taken_at = f"{photo.taken_at:%Y-%m-%d %H:%M}" if photo.taken_at else "brak daty"
    prefix = f"[{index}/{total}] {_relative(photo.path, config.input_dir)} ({taken_at})"
    label = _STATUS_LABELS[match.status]
    reason = f": {match.detail}" if match.detail else ""

    if match.status == MatchStatus.UNMATCHED:
        log(f"{prefix} -> pominięto ({match.detail})")
    elif dry_run:
        log(f"{prefix} -> {_relative(build_target_dir(config, photo, match), config.output_dir)} [{label}{reason}]")
    else:
        destination = place_photo(config, photo, match)
        log(f"{prefix} -> {_relative(destination, config.output_dir)} [{label}{reason}]")


def _describe_statuses(by_status: Counter[MatchStatus]) -> str:
    return ", ".join(f"{_STATUS_LABELS[status]}: {by_status[status]}" for status in _STATUS_LABELS if by_status[status]) or "brak plików"


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
