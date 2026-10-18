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


def exif_taken_at(data: dict) -> datetime | None:
    """When the photo was taken according to exiftool's JSON for one file, None if it doesn't say."""
    raw_datetime = data.get("DateTimeOriginal") or data.get("CreateDate")
    return _parse_exiftool_datetime(str(raw_datetime)) if raw_datetime else None


def exif_string(value) -> str | None:
    """A text tag (e.g. Model) with surrounding whitespace dropped; None when missing or blank."""
    if value is None:
        return None
    return str(value).strip() or None


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
        taken_at = exif_taken_at(data)
        camera_model = exif_string(data.get("Model"))
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


# Everything the catalog keeps about a file, read in one exiftool call per batch (see read_metadata_batch).
BATCH_TAGS = ("DateTimeOriginal", "CreateDate", "Make", "Model", "GPSLatitude", "GPSLongitude", "Keywords")


def read_metadata_batch(paths: list[Path]) -> dict[Path, dict]:
    """exiftool's JSON (with `-n`, so GPS comes as signed decimal degrees) for each of `paths`,
    read in a single exiftool process - starting the process costs far more than reading one
    file's tags, so this is what makes scanning thousands of files bearable.

    The paths go in through stdin (`-@ -`) rather than argv, so a batch is never limited by the
    command-line length. A file exiftool can't read is simply missing from the result; if
    exiftool itself isn't available, the result is empty.
    """
    if not paths:
        return {}
    args = ["exiftool", "-j", "-n", *(f"-{tag}" for tag in BATCH_TAGS), "-@", "-"]
    try:
        result = subprocess.run(
            args, input="\n".join(str(path) for path in paths), capture_output=True, text=True
        )
        entries = json.loads(result.stdout) if result.stdout.strip() else []
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {Path(entry["SourceFile"]): entry for entry in entries if "SourceFile" in entry and "Error" not in entry}


def iter_media_files(input_dir: Path):
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path
