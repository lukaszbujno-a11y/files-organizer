from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import RecognizedLocation


class LocationRecognizer(ABC):
    # Where the most recent `recognize` got its answer ("offline", "cache", "api"), or None when
    # no lookup happened (e.g. no GPS in the file) - used only for progress logs.
    last_source: str | None = None
    last_source_detail: str = ""

    @abstractmethod
    def recognize(self, path: Path) -> RecognizedLocation | None:
        ...
