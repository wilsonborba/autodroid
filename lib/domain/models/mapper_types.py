from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MapperMode(str, Enum):
    LIGHT = "light"
    MEDIUM = "medium"
    DEEP = "deep"


class MapperSessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MapperActionSafety(str, Enum):
    SAFE = "safe"
    DANGEROUS = "dangerous"


@dataclass(frozen=True)
class MapperLimits:
    max_depth: int
    max_actions: int
    max_scrolls: int


@dataclass(frozen=True)
class MapperRunConfig:
    package_name: str
    mode: MapperMode
    skip_dangerous_actions: bool = True
    override: bool = False
