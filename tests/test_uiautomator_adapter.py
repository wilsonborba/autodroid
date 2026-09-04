from __future__ import annotations

from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter


class FakeTouch:
    def __init__(self) -> None:
        self.down_calls: list[tuple[int, int]] = []
        self.up_calls: list[tuple[int, int]] = []

    def down(self, x: int, y: int) -> None:
        self.down_calls.append((x, y))

    def up(self, x: int, y: int) -> None:
        self.up_calls.append((x, y))


class FakeDevice:
    def __init__(self, *, raise_on_send: bool = False, raise_on_clipboard: bool = False) -> None:
        self.sent: list[tuple[str, bool]] = []
        self._raise_on_send = raise_on_send
        self._raise_on_clipboard = raise_on_clipboard
        self.double_clicked: list[tuple[int, int, float]] = []
        self.dragged: list[tuple[int, int, int, int, float]] = []
        self.clipboard_set: list[str] = []
        self.clipboard = ""
        self.touch = FakeTouch()

    def send_keys(self, text: str, clear: bool = False) -> None:
        if self._raise_on_send:
            raise RuntimeError("no IME available")
        self.sent.append((text, clear))

    def double_click(self, x: int, y: int, duration: float = 0.1) -> None:
        self.double_clicked.append((x, y, duration))

    def drag(self, sx: int, sy: int, ex: int, ey: int, duration: float = 0.5) -> None:
        self.dragged.append((sx, sy, ex, ey, duration))

    def set_clipboard(self, text: str, label: str | None = None) -> None:
        if self._raise_on_clipboard:
            raise RuntimeError("clipboard unavailable")
        self.clipboard_set.append(text)
        self.clipboard = text


def _adapter(device: FakeDevice) -> UiAutomatorAdapter:
    adapter = UiAutomatorAdapter("fake-serial")
    adapter._device = device
    return adapter


class FakeSelector:
    def __init__(self, *, found: bool) -> None:
        self._found = found
        self.clicked = False
        self.pinched_in: tuple[int, int] | None = None
        self.pinched_out: tuple[int, int] | None = None

    def exists(self, timeout: float = 1) -> bool:
        return self._found

    def click(self) -> None:
        self.clicked = True

    def pinch_in(self, percent: int = 100, steps: int = 50) -> None:
        self.pinched_in = (percent, steps)

    def pinch_out(self, percent: int = 100, steps: int = 50) -> None:
        self.pinched_out = (percent, steps)


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


def test_double_click_bounds_taps_twice_at_the_center() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.double_click_bounds("[0,0][20,10]")

    assert result is True
    assert device.double_clicked == [(10, 5, 0.1)]


def test_double_click_bounds_passes_duration_through() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    adapter.double_click_bounds("[0,0][20,10]", duration=0.3)

    assert device.double_clicked == [(10, 5, 0.3)]


def test_double_click_bounds_returns_false_on_unparseable_bounds() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.double_click_bounds("not-bounds")

    assert result is False
    assert device.double_clicked == []


def test_drag_bounds_drags_from_the_center_of_one_region_to_another() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.drag_bounds("[0,0][20,10]", "[100,100][120,110]")

    assert result is True
    assert device.dragged == [(10, 5, 110, 105, 0.5)]


def test_drag_bounds_returns_false_if_either_side_is_unparseable() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.drag_bounds("[0,0][20,10]", "not-bounds")

    assert result is False
    assert device.dragged == []


def test_pinch_by_resource_id_in() -> None:
    device = FakeResourceIdDevice(found=True)
    adapter = _adapter(device)

    result = adapter.pinch_by_resource_id("com.instagram.android:id/photo", direction="in", percent=80, steps=30)

    assert result is True
    assert device.selector.pinched_in == (80, 30)
    assert device.selector.pinched_out is None


def test_pinch_by_resource_id_out() -> None:
    device = FakeResourceIdDevice(found=True)
    adapter = _adapter(device)

    result = adapter.pinch_by_resource_id("com.instagram.android:id/photo", direction="out")

    assert result is True
    assert device.selector.pinched_out == (100, 50)


def test_pinch_by_resource_id_rejects_unsupported_direction() -> None:
    device = FakeResourceIdDevice(found=True)
    adapter = _adapter(device)

    result = adapter.pinch_by_resource_id("com.instagram.android:id/photo", direction="sideways")

    assert result is False


def test_pinch_by_resource_id_returns_false_when_not_found() -> None:
    device = FakeResourceIdDevice(found=False)
    adapter = _adapter(device)

    result = adapter.pinch_by_resource_id("missing", direction="in")

    assert result is False


def test_set_clipboard_writes_through_to_the_device() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.set_clipboard("copied text")

    assert result is True
    assert device.clipboard_set == ["copied text"]


def test_set_clipboard_returns_false_instead_of_raising() -> None:
    device = FakeDevice(raise_on_clipboard=True)
    adapter = _adapter(device)

    result = adapter.set_clipboard("copied text")

    assert result is False


def test_get_clipboard_reads_the_device_clipboard() -> None:
    device = FakeDevice()
    device.clipboard = "already there"
    adapter = _adapter(device)

    assert adapter.get_clipboard() == "already there"


def test_get_clipboard_returns_empty_string_when_device_reports_none() -> None:
    device = FakeDevice()
    device.clipboard = None
    adapter = _adapter(device)

    assert adapter.get_clipboard() == ""


def test_press_hold_start_and_release_touch_down_then_up_at_the_center() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    started = adapter.press_hold_start("[0,0][20,10]")
    released = adapter.press_hold_release("[0,0][20,10]")

    assert started is True
    assert released is True
    assert device.touch.down_calls == [(10, 5)]
    assert device.touch.up_calls == [(10, 5)]


def test_press_hold_start_returns_false_on_unparseable_bounds() -> None:
    device = FakeDevice()
    adapter = _adapter(device)

    result = adapter.press_hold_start("not-bounds")

    assert result is False
    assert device.touch.down_calls == []
