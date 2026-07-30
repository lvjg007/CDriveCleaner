from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from src.models.items import CleanItem

ProgressCb = Callable[[str, float], None]


class Scanner(ABC):
    name: str = "base"

    @abstractmethod
    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        raise NotImplementedError
