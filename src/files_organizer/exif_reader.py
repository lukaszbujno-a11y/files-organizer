from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image

from .models import Photo

_DATETIME_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal")
_MODEL_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "Model")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".heic", ".tiff", ".png"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES


def read_photo_metadata(path: Path) -> Photo:
    taken_at: datetime | None = None
    camera_model: str | None = None

    try:
        with Image.open(path) as image:
            exif = image.getexif()
            raw_datetime = exif.get(_DATETIME_TAG)
            if raw_datetime:
                taken_at = datetime.strptime(raw_datetime, "%Y:%m:%d %H:%M:%S")
            raw_model = exif.get(_MODEL_TAG)
            if raw_model:
                camera_model = raw_model.strip()
    except Exception:
        pass

    if taken_at is None:
        taken_at = datetime.fromtimestamp(path.stat().st_mtime)

    return Photo(path=path, taken_at=taken_at, camera_model=camera_model)


def iter_media_files(input_dir: Path):
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path
