from __future__ import annotations

from lib.domain.models.mapper_types import MapperActionSafety
from lib.domain.services.mapper_safety_service import MapperSafetyService


def test_mapper_safety_marks_dangerous_patterns() -> None:
    service = MapperSafetyService()

    safety = service.classify({"resource_id": "button_delete_account"}, "Delete account")

    assert safety == MapperActionSafety.DANGEROUS


def test_mapper_safety_marks_safe_actions() -> None:
    service = MapperSafetyService()

    safety = service.classify({"resource_id": "profile_button"}, "View Profile")

    assert safety == MapperActionSafety.SAFE


def test_is_peek_candidate_matches_known_patterns() -> None:
    service = MapperSafetyService()

    assert service.is_peek_candidate({"resource_id": "message_btn"}, "Message") is True
    assert service.is_peek_candidate({"resource_id": "overflow_menu"}, None) is True
    assert service.is_peek_candidate({"resource_id": "profile_button"}, "View Profile") is False
