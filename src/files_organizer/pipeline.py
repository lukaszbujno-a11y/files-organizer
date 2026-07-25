from __future__ import annotations

import threading
from typing import Callable

from .calendar_sources import filter_events_by_tag, get_calendar_source
from .config import Config
from .exif_reader import iter_media_files, read_photo_metadata
from .matcher import MatchStatus, match_photo_to_event
from .organizer import build_target_dir, place_photo

LogFn = Callable[[str], None]


def run_pipeline(config: Config, dry_run: bool, log: LogFn, stop_event: threading.Event | None = None) -> None:
    """Match every media file under config.input_dir to a calendar event and file it away.

    Shared between the CLI loop and the GUI's background worker thread; `log` receives
    one line per processed file so both can render it (terminal echo / GUI log widget).

    `stop_event`, if given, is checked *between* files only, never mid-copy/move — so a
    requested stop always leaves the file system in a consistent state (every file that
    was started is finished; nothing is left half-copied). The caller is responsible for
    reporting whether the run ended early (`stop_event.is_set()` after this returns).
    """
    events = []
    if config.calendar:
        calendar_source = get_calendar_source(config.calendar)
        events = filter_events_by_tag(calendar_source.get_events(), config.include_tags)

    for path in iter_media_files(config.input_dir):
        if stop_event is not None and stop_event.is_set():
            return

        photo = read_photo_metadata(path)
        match = match_photo_to_event(photo, events, margin_hours=config.margin_hours)

        taken_at = f"{photo.taken_at:%Y-%m-%d %H:%M:%S}" if photo.taken_at else "unknown date"

        if match.status == MatchStatus.UNMATCHED:
            log(f"{photo.path} ({taken_at}) -> skipped (no matching calendar event)")
        elif dry_run:
            log(f"{photo.path} ({taken_at}) -> {build_target_dir(config, photo, match)}")
        else:
            destination = place_photo(config, photo, match)
            log(f"{photo.path} ({taken_at}) -> {destination}")
