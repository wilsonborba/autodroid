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


def test_fingerprint_still_distinguishes_generic_rows_with_different_text() -> None:
    # a settings menu and a profile menu can share the exact same generic row layout in a real
    # Android app (RecyclerView reusing resource_id across rows), only the label tells them
    # apart. `fingerprint()` (screen identity) must keep telling them apart (issue #25).
    service = MapperFingerprintService()
    settings_menu = [{"resource_id": "menu_row", "text": "Notifications", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False}]
    profile_menu = [{"resource_id": "menu_row", "text": "Edit profile", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False}]

    assert service.fingerprint(settings_menu) != service.fingerprint(profile_menu)


def test_structural_signature_ignores_text_and_content_desc() -> None:
    service = MapperFingerprintService()
    post_one = [{"resource_id": "feed_card", "text": "First post", "content_desc": "posted by alice", "class_name": "CardView", "clickable": True, "scrollable": True}]
    post_two = [{"resource_id": "feed_card", "text": "Second post", "content_desc": "posted by bob", "class_name": "CardView", "clickable": True, "scrollable": True}]

    assert service.structural_signature(post_one) == service.structural_signature(post_two)
    assert service.fingerprint(post_one) != service.fingerprint(post_two)  # identity still differs


def test_structural_signature_distinguishes_genuinely_different_layouts() -> None:
    service = MapperFingerprintService()
    feed_card = [{"resource_id": "feed_card", "text": "x", "content_desc": "", "class_name": "CardView", "clickable": True, "scrollable": True}]
    settings_row = [{"resource_id": "settings_row", "text": "y", "content_desc": "", "class_name": "TextView", "clickable": True, "scrollable": False}]

    assert service.structural_signature(feed_card) != service.structural_signature(settings_row)
