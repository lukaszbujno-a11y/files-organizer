from __future__ import annotations

import shutil
from pathlib import Path

from .config import Config
from .matcher import MatchResult, MatchStatus
from .models import Photo


def build_target_dir(config: Config, photo: Photo, match: MatchResult) -> Path:
    base = config.output_dir

    parent_dir = None
    if match.event and match.event.tag:
        mapping = config.phone_mapping.get(match.event.tag)
        if mapping and mapping.camera_model == photo.camera_model:
            parent_dir = mapping.parent_dir

    if match.status == MatchStatus.MATCHED:
        event = match.event
        year, month = f"{event.start:%Y}", f"{event.start:%m}"
        folder_name = f"{event.start:%Y-%m-%d} {event.name}".strip()
        target = base / year / month / folder_name
    elif match.status == MatchStatus.OVERLAPPING:
        year, month = f"{photo.taken_at:%Y}", f"{photo.taken_at:%m}"
        folder_name = f"{photo.taken_at:%Y-%m-%d} {config.overlap_dir_name}"
        target = base / year / month / folder_name
    else:
        target = base / config.unmatched_dir_name / f"{photo.taken_at:%Y-%m}"

    if parent_dir:
        target = base / parent_dir / target.relative_to(base)

    return target


def place_photo(config: Config, photo: Photo, match: MatchResult) -> Path:
    target_dir = build_target_dir(config, photo, match)
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / photo.path.name

    if config.mode == "move":
        shutil.move(str(photo.path), str(destination))
    else:
        shutil.copy2(str(photo.path), str(destination))

    return destination
