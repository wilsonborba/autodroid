from __future__ import annotations

from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter


class FakeDevice:
    def __init__(self, *, raise_on_send: bool = False) -> None:
        self.sent: list[tuple[str, bool]] = []
        self._raise_on_send = raise_on_send

    def send_keys(self, text: str, clear: bool = False) -> None:
        if self._raise_on_send:
            raise RuntimeError("no IME available")
        self.sent.append((text, clear))


def _adapter(device: FakeDevice) -> UiAutomatorAdapter:
    adapter = UiAutomatorAdapter("fake-serial")
    adapter._device = device
    return adapter


def test_type_text_sends_keys_to_the_focused_field() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.type_text("hello world")

    assert result is True
    assert device.sent == [("hello world", False)]


def test_type_text_passes_clear_flag_through() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.type_text("replacement", clear=True)

    assert result is True
    assert device.sent == [("replacement", True)]


def test_type_text_returns_false_instead_of_raising_on_device_failure() -> None:
    device = FakeDevice(raise_on_send=True)
    adapter = _adapter(device)

    result = adapter.type_text("hello")

    assert result is False
