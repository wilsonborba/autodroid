from __future__ import annotations

from lib.domain.models.mapper_types import MapperLimits, MapperMode


class MapperModeService:
    LIMITS = {
        MapperMode.LIGHT: MapperLimits(max_depth=1, max_actions=8, max_scrolls=0),
        MapperMode.MEDIUM: MapperLimits(max_depth=2, max_actions=40, max_scrolls=2),
        MapperMode.DEEP: MapperLimits(max_depth=4, max_actions=120, max_scrolls=10),
    }

    def get_limits(self, mode: MapperMode) -> MapperLimits:
        return self.LIMITS[mode]
