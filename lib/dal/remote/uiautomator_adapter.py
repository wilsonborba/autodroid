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
        if u2 is None:
            raise RuntimeError("uiautomator2 is not available in this environment")
        if self._device is None:
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

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.device.screenshot(str(path))
        self.logger.debug("Saved screenshot to %s", path)
        return path

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
