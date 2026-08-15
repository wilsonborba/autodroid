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
    assert light.repeat_signature_threshold < medium.repeat_signature_threshold < deep.repeat_signature_threshold


def test_repeat_signature_threshold_stays_well_below_the_scroll_safety_ceiling() -> None:
    # repeat_signature_threshold is what actually stops a scrolling screen (issue #25),
    # max_scrolls is only the safety ceiling behind it, it should rarely be the deciding factor
    service = MapperModeService()

    for mode in (MapperMode.LIGHT, MapperMode.MEDIUM, MapperMode.DEEP):
        limits = service.get_limits(mode)
        assert limits.repeat_signature_threshold < limits.max_scrolls
