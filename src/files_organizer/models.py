from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Event:
    name: str
    start: datetime
    end: datetime
    location: str | None = None
    tag: str | None = None


@dataclass(frozen=True)
class Photo:
    path: Path
    taken_at: datetime | None
    camera_model: str | None = None


@dataclass(frozen=True)
class RecognizedPerson:
    name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x, y, width, height


@dataclass(frozen=True)
class RecognizedLocation:
    city: str
    country: str
    latitude: float
    longitude: float
