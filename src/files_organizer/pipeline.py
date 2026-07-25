from __future__ import annotations

from typing import Callable

from .calendar_sources import get_calendar_source
from .config import Config
from .exif_reader import iter_media_files, read_photo_metadata
from .matcher import MatchStatus, match_photo_to_event
from .organizer import build_target_dir, place_photo

LogFn = Callable[[str], None]


def run_pipeline(config: Config, dry_run: bool, log: LogFn) -> None:
    """Match every media file under config.input_dir to a calendar event and file it away.

    Shared between the CLI loop and the GUI's background worker thread; `log` receives
    one line per processed file so both can render it (terminal echo / GUI log widget).
    """
    events = []
    if config.calendar:
        calendar_source = get_calendar_source(config.calendar)
        events = calendar_source.get_events()

    for path in iter_media_files(config.input_dir):
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
