from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .models import Photo

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".heic", ".tiff", ".png"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES

_DATETIME_RE = re.compile(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")


def _parse_exiftool_datetime(value: str) -> datetime | None:
    match = _DATETIME_RE.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def read_photo_metadata(path: Path) -> Photo:
    taken_at: datetime | None = None
    camera_model: str | None = None

    try:
        result = subprocess.run(
            ["exiftool", "-j", "-DateTimeOriginal", "-CreateDate", "-Model", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)[0]
        raw_datetime = data.get("DateTimeOriginal") or data.get("CreateDate")
        if raw_datetime:
            taken_at = _parse_exiftool_datetime(raw_datetime)
        raw_model = data.get("Model")
        if raw_model:
            camera_model = raw_model.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, IndexError):
        pass

    if taken_at is None:
        taken_at = datetime.fromtimestamp(path.stat().st_mtime)

    return Photo(path=path, taken_at=taken_at, camera_model=camera_model)


def read_gps(path: Path) -> tuple[float, float] | None:
    """Return `(latitude, longitude)` from `path`'s EXIF GPS tags, or None if absent/unreadable."""
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-n", "-GPSLatitude", "-GPSLongitude", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)[0]
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, IndexError):
        return None

    latitude = data.get("GPSLatitude")
    longitude = data.get("GPSLongitude")
    if latitude is None or longitude is None:
        return None
    return float(latitude), float(longitude)


def iter_media_files(input_dir: Path):
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path
