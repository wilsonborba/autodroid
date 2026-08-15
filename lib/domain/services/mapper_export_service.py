from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class MapperExportService(ABC):
    @abstractmethod
    def export_session(self, session_id: int, output_dir: Path) -> Path:
        raise NotImplementedError
