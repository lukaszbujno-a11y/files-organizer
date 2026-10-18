from __future__ import annotations

import threading
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
    events = []
    if config.calendar and "calendar" in config.rules:
        calendar_source = get_calendar_source(config.calendar)
        events = filter_events_by_tag(calendar_source.get_events(), config.include_tags)

    location_recognizer = None
    if "location" in config.rules:
        location_recognizer = get_location_recognizer(config.location_recognition or {})

    log(f"Odczytuję metadane plików z {config.input_dir}…")
    photos = []
    for path in iter_media_files(config.input_dir):
        if stop_event is not None and stop_event.is_set():
            return
        photos.append(read_photo_metadata(path))

    if stop_event is not None and stop_event.is_set():
        return
    classified = classify_photos(photos, config, events, location_recognizer, log=log)
    log(f"Przeanalizowano {len(photos)} plików (reguły: {', '.join(config.rules)}).")

    for photo, match in classified:
        if stop_event is not None and stop_event.is_set():
            return

        taken_at = f"{photo.taken_at:%Y-%m-%d %H:%M:%S}" if photo.taken_at else "unknown date"

        if match.status == MatchStatus.UNMATCHED:
            log(f"{photo.path} ({taken_at}) -> skipped (no rule matched)")
        elif dry_run:
            log(f"{photo.path} ({taken_at}) -> {build_target_dir(config, photo, match)}")
        else:
            destination = place_photo(config, photo, match)
            log(f"{photo.path} ({taken_at}) -> {destination}")
