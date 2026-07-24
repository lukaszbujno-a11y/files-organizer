from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Event


class CalendarSource(ABC):
    @abstractmethod
    def get_events(self) -> list[Event]:
        ...
