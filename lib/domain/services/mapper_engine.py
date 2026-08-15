from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lib.domain.models.mapper_types import MapperRunConfig


class MapperEngine(ABC):
    @abstractmethod
    def run(self, config: MapperRunConfig) -> dict[str, Any]:
        raise NotImplementedError
