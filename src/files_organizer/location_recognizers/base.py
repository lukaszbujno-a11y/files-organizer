from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import RecognizedLocation


class LocationRecognizer(ABC):
    @abstractmethod
    def recognize(self, path: Path) -> RecognizedLocation | None:
        ...
