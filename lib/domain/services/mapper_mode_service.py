from __future__ import annotations

from lib.domain.models.mapper_types import MapperLimits, MapperMode


class MapperModeService:
    """The modes differ mainly in how deep/thorough the exploration goes, not in an arbitrary
    action budget (issue #25): light is a shallow, broad sweep (quick overview of the whole
    app), medium follows a link 2-3 levels deep, deep maps everything, full stop (issue #36):
    `max_actions` for deep is not a product-level stopping point, it's set so high it should
    never actually be the reason exploration ends. `max_depth` for deep is a technical ceiling
    on Python's call stack (each screen level recurses), not a coverage limit either, 50 is
    generous enough that real, distinct content practically never needs to go that deep once
    structural dedup (issue #30) is already collapsing repeated screen types well before then.
    Light and medium keep small, deliberate budgets, they're quick partial sweeps by design, that
    part is unchanged. `max_scrolls` is the hard per-screen ceiling, always in effect (never
    removed, issue #34); `max_consecutive_empty_scrolls` is a smarter early exit on top of it,
    scrolling stops as soon as that many scrolls in a row found zero new nodes, without needing
    to burn through the whole ceiling on a screen that's genuinely done."""

    # not "unlimited" (an int column, and a real value keeps every comparison simple), just high
    # enough that it is never the actual reason a deep run stops (issue #36)
    DEEP_ACTIONS_CEILING = 10**9

    LIMITS = {
        MapperMode.LIGHT: MapperLimits(max_depth=1, max_actions=8, max_scrolls=30, max_consecutive_empty_scrolls=3),
        MapperMode.MEDIUM: MapperLimits(max_depth=3, max_actions=60, max_scrolls=75, max_consecutive_empty_scrolls=5),
        MapperMode.DEEP: MapperLimits(max_depth=50, max_actions=DEEP_ACTIONS_CEILING, max_scrolls=300, max_consecutive_empty_scrolls=8),
    }

    def get_limits(self, mode: MapperMode) -> MapperLimits:
        return self.LIMITS[mode]
