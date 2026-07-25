from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import RecognizedPerson


class FaceRecognizer(ABC):
    @abstractmethod
    def recognize(self, path: Path) -> list[RecognizedPerson]:
        ...
