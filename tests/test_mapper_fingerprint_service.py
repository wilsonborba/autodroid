from __future__ import annotations

from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService


def test_fingerprint_is_stable_for_reordered_nodes() -> None:
    service = MapperFingerprintService()
    left = [
        {"resource_id": "a", "text": "Profile", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False},
        {"resource_id": "b", "text": "Settings", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False},
    ]
    right = list(reversed(left))

    assert service.fingerprint(left) == service.fingerprint(right)


def test_equivalent_returns_true_for_same_structural_screen() -> None:
    service = MapperFingerprintService()
    left = [{"resource_id": "a", "text": "Profile", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False}]
    right = [{"resource_id": "a", "text": "Profile", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False}]

    assert service.equivalent(left, right) is True
