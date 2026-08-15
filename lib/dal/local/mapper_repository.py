from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MapperRepository(ABC):
    @abstractmethod
    def create_session(self, **kwargs: Any) -> Any:
        raise NotImplementedError
