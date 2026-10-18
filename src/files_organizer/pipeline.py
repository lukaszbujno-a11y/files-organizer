from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .calendar_sources import filter_events_by_tag, get_calendar_source
from .catalog import Catalog, CatalogLocationRecognizer
from .config import Config
from .exif_reader import iter_media_files, read_photo_metadata
from .location_recognizers import LocationRecognizer, get_location_recognizer
from .matcher import MatchResult, MatchStatus
from .models import Photo
from .organizer import build_target_dir, place_photo
from .rules import classify_photos, describe_location_stats

LogFn = Callable[[str], None]


def run_pipeline(
    config: Config,
    dry_run: bool,
    log: LogFn,
    stop_event: threading.Event | None = None,
    catalog: Catalog | None = None,
) -> None:
    """Classify every media file under config.input_dir (see `rules.classify_photos`) and file it away.

    Shared between the CLI loop and the GUI's background worker thread; `log` receives
    one line per processed file so both can render it (terminal echo / GUI log widget).

    `stop_event`, if given, is checked *between* files only, never mid-copy/move — so a
    requested stop always leaves the file system in a consistent state (every file that
    was started is finished; nothing is left half-copied). The caller is responsible for
    reporting whether the run ended early (`stop_event.is_set()` after this returns).

    With a `catalog`, the run starts with an incremental scan of input_dir (exiftool runs only
    for new/changed files); metadata, GPS and already resolved place names then come from the
    catalog, and every copied/moved file is recorded there under its new path.

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
    phases = (3 if two_pass else 2) + (1 if catalog is not None else 0)
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
        location_config = config.location_recognition or {}
        if catalog is None:
            location_recognizer = get_location_recognizer(location_config)
        else:
            location_recognizer = CatalogLocationRecognizer(
                get_location_recognizer(location_config, gps_reader=catalog.read_gps),
                catalog,
                source=f"{location_config.get('type', 'reverse_geocoder')}:{location_config.get('language', 'pl')}",
            )
        log(f"Lokalizacja: {location_config.get('type', 'reverse_geocoder')}")

    if catalog is None:
        paths = list(iter_media_files(config.input_dir))
        next_phase = 2
    else:
        phase_started = time.monotonic()
        log(f"[2/{phases}] Katalog: skan przyrostowy {config.input_dir} ({catalog.path})…")
        scan = catalog.scan(config.input_dir, log=log, should_stop=stopped)
        if scan.stopped:
            return
        log(f"[2/{phases}] Katalog: {scan.describe()} ({_elapsed(phase_started)})")
        paths = scan.paths
        next_phase = 3

    run = _Run(config, dry_run, log, stopped, events, location_recognizer, mode, catalog, next_phase, phases)
    if two_pass:
        _run_two_pass(run, paths)
    else:
        _run_streaming(run, paths)
    if not stopped():
        log(f"Zakończono; łącznie {_elapsed(started)}")


@dataclass(frozen=True)
class _Run:
    config: Config
    dry_run: bool
    log: LogFn
    stopped: Callable[[], bool]
    events: list
    location_recognizer: LocationRecognizer | None
    mode: str
    catalog: Catalog | None
    first_phase: int  # number of the first phase left after calendar (+ catalog scan)
    phases: int

    def phase(self, offset: int = 0) -> str:
        return f"[{self.first_phase + offset}/{self.phases}]"

    def read(self, path: Path) -> Photo:
        if self.catalog is None:
            return read_photo_metadata(path)
        entry = self.catalog.get(path) or self.catalog.refresh(path)
        return entry.to_photo(path) if entry is not None else read_photo_metadata(path)


def _run_two_pass(run: _Run, paths: list[Path]) -> None:
    config, log, stopped, analysis = run.config, run.log, run.stopped, run.phase()
    phase_started = time.monotonic()
    log(f"{analysis} Analiza (reguła 'date' potrzebuje wszystkich zdjęć naraz): odczyt metadanych {len(paths)} plików…")
    photos = []
    last_progress = time.monotonic()
    for index, path in enumerate(paths, start=1):
        if stopped():
            return
        photos.append(run.read(path))
        if index % 50 == 0 or time.monotonic() - last_progress >= 2:
            log(f"  metadane: {index}/{len(paths)} ({_elapsed(phase_started)})")
            last_progress = time.monotonic()
    log(f"{analysis} Analiza: metadane odczytane ({_elapsed(phase_started)})")

    classified = classify_photos(photos, config, run.events, run.location_recognizer, log=log, should_stop=stopped)
    if stopped():
        return
    by_status = Counter(match.status for _, match in classified)
    log(f"{analysis} Analiza zakończona ({_elapsed(phase_started)}) - {_describe_statuses(by_status)}")

    phase_started = time.monotonic()
    placing = run.phase(1)
    action = "Podgląd" if run.dry_run else run.mode.capitalize()
    skipped = by_status[MatchStatus.UNMATCHED]
    log(f"{placing} {action}: {len(classified) - skipped} plików, {skipped} pominiętych…")
    for index, (photo, match) in enumerate(classified, start=1):
        if stopped():
            return
        _place_and_log(run, photo, match, index, len(classified))
    log(f"{placing} {action} zakończone ({_elapsed(phase_started)})")


def _run_streaming(run: _Run, paths: list[Path]) -> None:
    config, log, stopped, placing = run.config, run.log, run.stopped, run.phase()
    action = "Podgląd" if run.dry_run else run.mode.capitalize()
    phase_started = time.monotonic()
    log(f"{placing} {action}: {len(paths)} plików, każdy od razu po analizie…")
    by_status: Counter[MatchStatus] = Counter()
    location_stats: Counter[str] = Counter()
    for index, path in enumerate(paths, start=1):
        if stopped():
            return
        photo = run.read(path)
        [(photo, match)] = classify_photos(
            [photo], config, run.events, run.location_recognizer, log=log, numbering=(index, len(paths)), location_stats=location_stats
        )
        by_status[match.status] += 1
        _place_and_log(run, photo, match, index, len(paths))

    log(f"{placing} {action} zakończone ({_elapsed(phase_started)}) - {_describe_statuses(by_status)}")
    if location_stats:
        log(f"  Lokalizacje: {describe_location_stats(location_stats)}")


def _place_and_log(run: _Run, photo: Photo, match: MatchResult, index: int, total: int) -> None:
    config, log = run.config, run.log
    taken_at = f"{photo.taken_at:%Y-%m-%d %H:%M}" if photo.taken_at else "brak daty"
    prefix = f"[{index}/{total}] {_relative(photo.path, config.input_dir)} ({taken_at})"
    label = _STATUS_LABELS[match.status]
    reason = f": {match.detail}" if match.detail else ""

    if match.status == MatchStatus.UNMATCHED:
        log(f"{prefix} -> pominięto ({match.detail})")
    elif run.dry_run:
        log(f"{prefix} -> {_relative(build_target_dir(config, photo, match), config.output_dir)} [{label}{reason}]")
    else:
        destination = place_photo(config, photo, match)
        if run.catalog is not None:
            run.catalog.record_placed(photo.path, destination, moved=config.mode == "move")
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
