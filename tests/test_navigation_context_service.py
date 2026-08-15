from __future__ import annotations

from lib.domain.services.navigation_context_service import NavigationContextService, ResumeContext


class FakeAdbAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def go_home(self) -> None:
        self.calls.append("home")

    def force_stop_app(self, package_name: str) -> None:
        self.calls.append(f"force-stop:{package_name}")

    def start_app(self, package_name: str) -> None:
        self.calls.append(f"start:{package_name}")


def test_prepare_fresh_app_launch_always_resets_to_home() -> None:
    adb = FakeAdbAdapter()
    service = NavigationContextService(adb)

    service.prepare_fresh_app_launch("com.linkedin.android")

    assert adb.calls == [
        "home",
        "force-stop:com.linkedin.android",
        "home",
        "start:com.linkedin.android",
    ]


def test_resume_context_stays_disabled_without_payload_flag() -> None:
    service = NavigationContextService(FakeAdbAdapter())

    context = service.load_resume_context({})

    assert context == ResumeContext(enabled=False)
    assert service.can_resume(context) is False
