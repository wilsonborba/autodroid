from __future__ import annotations

from lib.domain.adapters.linkedin.linkedin_adapter import LinkedInAdapter


class FakeUi:
    def __init__(self, exact: list[bool], contains: list[bool]) -> None:
        self.exact = exact
        self.contains = contains
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def click_first_by_text_or_description(self, *candidates: str) -> bool:
        self.calls.append(("exact", candidates))
        return self.exact.pop(0)

    def click_first_by_text_or_description_contains(self, *candidates: str) -> bool:
        self.calls.append(("contains", candidates))
        return self.contains.pop(0)


def build_adapter(fake_ui: FakeUi) -> LinkedInAdapter:
    adapter = LinkedInAdapter.__new__(LinkedInAdapter)
    adapter.ui = fake_ui
    return adapter


def test_open_profile_entrypoint_uses_direct_profile_shortcut_first() -> None:
    adapter = build_adapter(FakeUi(exact=[True], contains=[]))

    assert adapter._open_profile_entrypoint() is True
    assert adapter.ui.calls == [
        ("exact", ("Meu perfil", "Perfil", "My Profile", "View Profile", "Ver perfil")),
    ]


def test_open_profile_entrypoint_uses_menu_then_profile() -> None:
    adapter = build_adapter(FakeUi(exact=[False, True], contains=[True]))

    assert adapter._open_profile_entrypoint() is True
    assert adapter.ui.calls[0][0] == "exact"
    assert adapter.ui.calls[1][0] == "contains"
    assert adapter.ui.calls[2][0] == "exact"


def test_open_profile_entrypoint_returns_false_when_nothing_matches() -> None:
    adapter = build_adapter(FakeUi(exact=[False, False], contains=[False]))

    assert adapter._open_profile_entrypoint() is False
