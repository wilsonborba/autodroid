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


class MapperFlowFailureType(str, Enum):
    """Interaction failures only (issue #21): the map's selector didn't match reality anymore.
    Not a log of every step outcome, success and safety-skips are never recorded here."""

    SELECTOR_NOT_FOUND = "selector_not_found"
    CLICK_FAILED = "click_failed"
    UNSUPPORTED_ACTION_TYPE = "unsupported_action_type"
    EXCEPTION = "exception"


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
    complement: bool = False
