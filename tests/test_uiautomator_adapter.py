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


class FakeSelector:
    def __init__(self, *, found: bool) -> None:
        self._found = found
        self.clicked = False

    def exists(self, timeout: float = 1) -> bool:
        return self._found

    def click(self) -> None:
        self.clicked = True


class FakeResourceIdDevice:
    """Mimics the subset of uiautomator2's `device(**kwargs)` selector API that
    `click_by_resource_id` uses: calling the device with a selector kwarg returns an object with
    `exists()`/`click()`, same shape used by `click_first_by_text_or_description`."""

    def __init__(self, *, found: bool) -> None:
        self.calls: list[dict] = []
        self._found = found
        self.selector: FakeSelector | None = None

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        self.selector = FakeSelector(found=self._found)
        return self.selector


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


def test_click_by_resource_id_clicks_when_the_element_exists() -> None:
    device = FakeResourceIdDevice(found=True)
    adapter = _adapter(device)

    result = adapter.click_by_resource_id("com.instagram.android:id/reply_bar_edittext")

    assert result is True
    assert device.calls == [{"resourceId": "com.instagram.android:id/reply_bar_edittext"}]
    assert device.selector.clicked is True


def test_click_by_resource_id_returns_false_when_not_found() -> None:
    device = FakeResourceIdDevice(found=False)
    adapter = _adapter(device)

    result = adapter.click_by_resource_id("missing_id")

    assert result is False
    assert device.selector.clicked is False
