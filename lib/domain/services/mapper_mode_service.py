from __future__ import annotations

from lib.domain.models.mapper_types import MapperLimits, MapperMode


class MapperModeService:
    """The modes differ mainly in how deep/thorough the exploration goes, not in an arbitrary
    action budget (issue #25): light is a shallow, broad sweep (quick overview of the whole
    app), medium follows a link 2-3 levels deep, deep tries to map everything. `max_scrolls` is
    a safety ceiling, not the real stopping point for a scrolling screen: `repeat_signature_threshold`
    is what actually decides when a feed has been seen enough (see `MapperFingerprintService.
    structural_signature`)."""

    LIMITS = {
        MapperMode.LIGHT: MapperLimits(max_depth=1, max_actions=8, max_scrolls=30, repeat_signature_threshold=20),
        MapperMode.MEDIUM: MapperLimits(max_depth=3, max_actions=60, max_scrolls=75, repeat_signature_threshold=50),
        MapperMode.DEEP: MapperLimits(max_depth=8, max_actions=500, max_scrolls=300, repeat_signature_threshold=200),
    }

    def get_limits(self, mode: MapperMode) -> MapperLimits:
        return self.LIMITS[mode]
