from __future__ import annotations

from lib.domain.models.mapper_types import MapperMode
from lib.domain.services.mapper_mode_service import MapperModeService


def test_mapper_mode_limits_are_ordered_by_depth_and_actions() -> None:
    service = MapperModeService()

    light = service.get_limits(MapperMode.LIGHT)
    medium = service.get_limits(MapperMode.MEDIUM)
    deep = service.get_limits(MapperMode.DEEP)

    assert light.max_depth < medium.max_depth < deep.max_depth
    assert light.max_actions < medium.max_actions < deep.max_actions
    assert light.max_scrolls <= medium.max_scrolls <= deep.max_scrolls
    assert light.max_consecutive_empty_scrolls < medium.max_consecutive_empty_scrolls < deep.max_consecutive_empty_scrolls


def test_deep_mode_action_ceiling_is_a_technical_backstop_not_a_coverage_budget() -> None:
    # deep maps everything, it only stops on its own once nothing new is left (issue #36):
    # max_actions here must not be a realistic-to-hit product budget like light/medium's
    service = MapperModeService()

    deep = service.get_limits(MapperMode.DEEP)

    assert deep.max_actions == MapperModeService.DEEP_ACTIONS_CEILING
    assert deep.max_actions > 1_000_000


def test_max_consecutive_empty_scrolls_stays_well_below_the_scroll_safety_ceiling() -> None:
    # max_consecutive_empty_scrolls is what actually stops a scrolling screen (issue #25),
    # max_scrolls is only the safety ceiling behind it, it should rarely be the deciding factor
    service = MapperModeService()

    for mode in (MapperMode.LIGHT, MapperMode.MEDIUM, MapperMode.DEEP):
        limits = service.get_limits(mode)
        assert limits.max_consecutive_empty_scrolls < limits.max_scrolls
