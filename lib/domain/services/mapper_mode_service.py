from __future__ import annotations

from lib.domain.models.mapper_types import MapperLimits, MapperMode


class MapperModeService:
    """The modes differ mainly in how deep/thorough the exploration goes, not in an arbitrary
    action budget (issue #25): light is a shallow, broad sweep (quick overview of the whole
    app), medium follows a link 2-3 levels deep, deep tries to map everything. `max_scrolls` is
    the hard per-screen ceiling, always in effect (never removed, issue #34); `max_consecutive_
    empty_scrolls` is a smarter early exit on top of it, scrolling stops as soon as that many
    scrolls in a row found zero new nodes, without needing to burn through the whole ceiling on a
    screen that's genuinely done."""

    LIMITS = {
        MapperMode.LIGHT: MapperLimits(max_depth=1, max_actions=8, max_scrolls=30, max_consecutive_empty_scrolls=3),
        MapperMode.MEDIUM: MapperLimits(max_depth=3, max_actions=60, max_scrolls=75, max_consecutive_empty_scrolls=5),
        MapperMode.DEEP: MapperLimits(max_depth=8, max_actions=500, max_scrolls=300, max_consecutive_empty_scrolls=8),
    }

    def get_limits(self, mode: MapperMode) -> MapperLimits:
        return self.LIMITS[mode]
