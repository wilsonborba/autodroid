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
        try:
            left_top, right_bottom = bounds.strip('[]').split('][')
            x1, y1 = [int(value) for value in left_top.split(',')]
            x2, y2 = [int(value) for value in right_bottom.split(',')]
        except Exception:
            self.logger.debug("Unable to parse click bounds: %s", bounds)
            return False
        self.device.click((x1 + x2) // 2, (y1 + y2) // 2)
        time.sleep(1)
        return True

    def dump_hierarchy_text(self) -> str:
        return self.device.dump_hierarchy(compressed=False)
