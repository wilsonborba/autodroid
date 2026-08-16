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


def test_fingerprint_ignores_a_foreign_package_clock_that_changes_every_minute() -> None:
    # issue #47: a dump always includes whatever else is visible too (status bar clock, battery,
    # launcher nav icons), none of it belongs to the app being mapped, and the clock in
    # particular changes every minute. Left in, the exact same real screen gets a different
    # fingerprint depending on what time it happened to be dumped, so it's never recognized as
    # already-known and gets fully re-explored again and again.
    service = MapperFingerprintService()
    screen_at_1502 = [
        {"resource_id": "profile_header", "text": "Wilson Borba", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.target.testapp"},
        {"resource_id": "clock", "text": "3:02 PM", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.android.systemui"},
    ]
    screen_at_1504 = [
        {"resource_id": "profile_header", "text": "Wilson Borba", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.target.testapp"},
        {"resource_id": "clock", "text": "3:04 PM", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.android.systemui"},
    ]

    assert service.fingerprint(screen_at_1502) != service.fingerprint(screen_at_1504)  # unfiltered: still fooled by the clock
    assert service.fingerprint(screen_at_1502, "com.target.testapp") == service.fingerprint(screen_at_1504, "com.target.testapp")


def test_fingerprint_still_distinguishes_screens_that_differ_within_the_target_app() -> None:
    # the filter isn't a blanket "ignore everything different", it only drops foreign-package
    # noise; a real difference inside the app being mapped must still be caught
    service = MapperFingerprintService()
    profile_a = [{"resource_id": "profile_header", "text": "Alice", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.target.testapp"}]
    profile_b = [{"resource_id": "profile_header", "text": "Bob", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.target.testapp"}]

    assert service.fingerprint(profile_a, "com.target.testapp") != service.fingerprint(profile_b, "com.target.testapp")


def test_structural_signature_also_ignores_foreign_package_noise() -> None:
    service = MapperFingerprintService()
    at_1502 = [{"resource_id": "feed_card", "text": "x", "content_desc": "", "class_name": "CardView", "clickable": True, "scrollable": True, "package_name": "com.target.testapp"}, {"resource_id": "clock", "text": "3:02 PM", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.android.systemui"}]
    at_1504 = [{"resource_id": "feed_card", "text": "y", "content_desc": "", "class_name": "CardView", "clickable": True, "scrollable": True, "package_name": "com.target.testapp"}, {"resource_id": "clock", "text": "3:04 PM", "content_desc": "", "class_name": "TextView", "clickable": False, "scrollable": False, "package_name": "com.android.systemui"}]

    assert service.structural_signature(at_1502, "com.target.testapp") == service.structural_signature(at_1504, "com.target.testapp")
