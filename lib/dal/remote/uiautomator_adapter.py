from __future__ import annotations

import time
import xml.etree.ElementTree as et
from pathlib import Path
from typing import Any

from lib.core.logs import get_logger

try:
    import uiautomator2 as u2
except Exception:  # pragma: no cover - optional until runtime
    u2 = None


class UiAutomatorAdapter:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._device = None
        self.logger = get_logger(__name__)

    @property
    def device(self):
        # an already-set _device (a real connection, or a fake injected by a test) wins over the
        # availability check, same fix as the OCR adapter's equivalent property (issue #32)
        if self._device is not None:
            return self._device
        if u2 is None:
            raise RuntimeError("uiautomator2 is not available in this environment")
        self._device = u2.connect(self.serial)
        return self._device

    def app_start(self, package_name: str) -> None:
        self.logger.debug("Starting app %s", package_name)
        self.device.app_start(package_name, stop=False)
        time.sleep(3)

    def click_first_by_text_or_description(self, *candidates: str) -> bool:
        for candidate in candidates:
            selector = self.device(text=candidate)
            if selector.exists(timeout=1):
                selector.click()
                time.sleep(1)
                return True
            selector = self.device(description=candidate)
            if selector.exists(timeout=1):
                selector.click()
                time.sleep(1)
                return True
        return False

    def click_first_by_text_or_description_contains(self, *candidates: str) -> bool:
        nodes = self.dump_nodes()
        for candidate in candidates:
            lowered_candidate = candidate.lower()
            for node in nodes:
                text = str(node.get("text", "")).strip()
                content_desc = str(node.get("content_desc", "")).strip()
                if text and lowered_candidate in text.lower():
                    if self.click_first_by_text_or_description(text):
                        return True
                if content_desc and lowered_candidate in content_desc.lower():
                    if self.click_first_by_text_or_description(content_desc):
                        return True
        return False

    def click_by_resource_id(self, resource_id: str) -> bool:
        # resource_id is the stable identifier apps expose for a UI element (issue #18's own
        # spec called it out as the resilient option, ahead of text/content_desc): a compose bar
        # or an action button keeps the same resource_id across runs even when the text on it is
        # dynamic (e.g. Instagram's reply field shows "Reply to <contact>", the contact changes,
        # the resource_id "reply_bar_edittext" doesn't). Only safe for elements that are unique
        # on screen; a resource_id shared by every row of a list still needs text/position to
        # pick one specific row.
        selector = self.device(resourceId=resource_id)
        if selector.exists(timeout=1):
            selector.click()
            time.sleep(1)
            return True
        return False

    def dump_nodes(self) -> list[dict[str, Any]]:
        self.logger.debug("Dumping UI hierarchy")
        hierarchy = self.device.dump_hierarchy(compressed=False)
        root = et.fromstring(hierarchy)
        nodes: list[dict[str, Any]] = []
        for node in root.iter("node"):
            item = {
                "text": (node.attrib.get("text") or "").strip(),
                "content_desc": (node.attrib.get("content-desc") or "").strip(),
                "resource_id": (node.attrib.get("resource-id") or "").strip(),
                "class_name": (node.attrib.get("class") or "").strip(),
                "bounds": (node.attrib.get("bounds") or "").strip(),
                "clickable": (node.attrib.get("clickable") or "false") == "true",
                "enabled": (node.attrib.get("enabled") or "true") == "true",
                "checkable": (node.attrib.get("checkable") or "false") == "true",
                "checked": (node.attrib.get("checked") or "false") == "true",
                "focusable": (node.attrib.get("focusable") or "false") == "true",
                "scrollable": (node.attrib.get("scrollable") or "false") == "true",
                "long_clickable": (node.attrib.get("long-clickable") or "false") == "true",
                "package_name": (node.attrib.get("package") or "").strip(),
            }
            if item["text"] or item["content_desc"] or item["resource_id"]:
                nodes.append(item)
        self.logger.debug("Dumped %s UI nodes", len(nodes))
        return nodes

    def swipe_up(self) -> None:
        self.device.swipe_ext("up", scale=0.8)
        time.sleep(1)

    def swipe_down(self) -> None:
        self.device.swipe_ext("down", scale=0.8)
        time.sleep(1)

    def _parse_bounds(self, bounds: str) -> tuple[int, int, int, int] | None:
        try:
            left_top, right_bottom = bounds.strip('[]').split('][')
            x1, y1 = [int(value) for value in left_top.split(',')]
            x2, y2 = [int(value) for value in right_bottom.split(',')]
            return x1, y1, x2, y2
        except Exception:
            self.logger.debug("Unable to parse bounds: %s", bounds)
            return None

    def swipe_bounds(self, bounds: str, direction: str, distance: int | None = None) -> bool:
        # a directional swipe anchored to one element's exact "[x1,y1][x2,y2]" region instead of
        # the whole screen (swipe_up/swipe_down): some gestures only register when they start on
        # the element itself, e.g. swiping a specific chat message sideways to reveal its reply
        # action, not just anywhere on screen
        parsed = self._parse_bounds(bounds)
        if parsed is None:
            return False
        x1, y1, x2, y2 = parsed
        offsets = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if direction not in offsets:
            self.logger.debug("Unsupported swipe direction: %s", direction)
            return False
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        sign_x, sign_y = offsets[direction]
        span = distance if distance is not None else max(min((x2 - x1) if sign_x else (y2 - y1), 400), 150)
        self.device.swipe(cx, cy, cx + sign_x * span, cy + sign_y * span, duration=0.2)
        time.sleep(1)
        return True

    def long_click_bounds(self, bounds: str, duration: float | None = None) -> bool:
        # press-and-hold on an exact "[x1,y1][x2,y2]" region, same target shape as click_bounds:
        # a touchscreen has no left/right mouse button, this is its equivalent of a right-click,
        # the gesture most apps use to surface a contextual menu (reply, forward, pin, delete, ...)
        # on an element instead of activating it. A fixed, decided-in-advance duration: for a
        # caller-timed hold instead (recording a voice message), see press_hold_start/_release.
        parsed = self._parse_bounds(bounds)
        if parsed is None:
            return False
        x1, y1, x2, y2 = parsed
        self.device.long_click((x1 + x2) // 2, (y1 + y2) // 2, duration=duration or 0.8)
        time.sleep(1)
        return True

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.device.screenshot(str(path))
        self.logger.debug("Saved screenshot to %s", path)
        return path

    def type_text(self, text: str, *, clear: bool = False) -> bool:
        # types into whatever's currently focused, same field a prior click/click_bounds put the
        # cursor in: it is deliberately not "click this field and type", one thing per call, same
        # shape as every other action here (issue #35)
        try:
            self.device.send_keys(text, clear=clear)
        except Exception:
            self.logger.debug("Unable to type text: %r", text)
            return False
        time.sleep(1)
        return True

    def click_bounds(self, bounds: str) -> bool:
        parsed = self._parse_bounds(bounds)
        if parsed is None:
            return False
        x1, y1, x2, y2 = parsed
        self.device.click((x1 + x2) // 2, (y1 + y2) // 2)
        time.sleep(1)
        return True

    def dump_hierarchy_text(self) -> str:
        return self.device.dump_hierarchy(compressed=False)

    def double_click_bounds(self, bounds: str, duration: float | None = None) -> bool:
        # two quick taps on the same point, the standard mobile-design gesture for "like" in
        # social apps (issue #62): distinct from long_click_bounds (one press held down) and from
        # calling click_bounds twice (uiautomator2's device.double_click controls the gap between
        # taps itself, calling click() twice from here wouldn't reliably land within the OS's
        # double-tap window)
        parsed = self._parse_bounds(bounds)
        if parsed is None:
            return False
        x1, y1, x2, y2 = parsed
        self.device.double_click((x1 + x2) // 2, (y1 + y2) // 2, duration=duration or 0.1)
        time.sleep(1)
        return True

    def drag_bounds(self, from_bounds: str, to_bounds: str, duration: float | None = None) -> bool:
        # press down on one element, move, release on another (issue #62): design taxonomy calls
        # this "drag" as distinct from "swipe"/"pan", the difference that matters here is drag
        # has an actual drop target (reordering a list, moving a file into a folder), swipe_bounds
        # only has a direction and a distance, there's nothing at the far end it's aiming for
        start = self._parse_bounds(from_bounds)
        end = self._parse_bounds(to_bounds)
        if start is None or end is None:
            return False
        sx1, sy1, sx2, sy2 = start
        ex1, ey1, ex2, ey2 = end
        self.device.drag((sx1 + sx2) // 2, (sy1 + sy2) // 2, (ex1 + ex2) // 2, (ey1 + ey2) // 2, duration=duration or 0.5)
        time.sleep(1)
        return True

    def pinch_by_resource_id(self, resource_id: str, *, direction: str, percent: int = 100, steps: int = 50) -> bool:
        # zoom in/out (issue #62): uiautomator2 only exposes pinch on a selected widget
        # (`device(...).pinch_in()/.pinch_out()`), not as a raw two-point gesture on bare
        # coordinates the way click/swipe/drag are, so this one is resource_id-only, no bounds
        # variant. Only meaningful on a widget that actually handles pinch itself (a photo/map
        # view), not on arbitrary screen regions.
        if direction not in ("in", "out"):
            self.logger.debug("Unsupported pinch direction: %s", direction)
            return False
        selector = self.device(resourceId=resource_id)
        if not selector.exists(timeout=1):
            return False
        if direction == "in":
            selector.pinch_in(percent=percent, steps=steps)
        else:
            selector.pinch_out(percent=percent, steps=steps)
        time.sleep(1)
        return True

    def get_clipboard(self) -> str:
        return self.device.clipboard or ""

    def set_clipboard(self, text: str) -> bool:
        # write-then-paste is how a real user fills a field from clipboard instead of typing
        # every character (issue #62): type_text (send_keys) always simulates keystrokes, this is
        # the other half, needed together with a later click on a "Paste" menu item or a
        # long-press-then-paste sequence
        try:
            self.device.set_clipboard(text)
        except Exception:
            self.logger.debug("Unable to set clipboard: %r", text)
            return False
        return True

    def press_hold_start(self, bounds: str) -> bool:
        # first half of a caller-controlled press-and-release (issue #62): long_click_bounds only
        # supports a duration decided in advance, this is for the opposite case, holding a
        # position until some other condition is met (recording a voice message: hold while
        # audio captures, release whenever the caller decides to stop, not a fixed 0.8s guess)
        parsed = self._parse_bounds(bounds)
        if parsed is None:
            return False
        x1, y1, x2, y2 = parsed
        self.device.touch.down((x1 + x2) // 2, (y1 + y2) // 2)
        return True

    def press_hold_release(self, bounds: str) -> bool:
        parsed = self._parse_bounds(bounds)
        if parsed is None:
            return False
        x1, y1, x2, y2 = parsed
        self.device.touch.up((x1 + x2) // 2, (y1 + y2) // 2)
        time.sleep(1)
        return True
