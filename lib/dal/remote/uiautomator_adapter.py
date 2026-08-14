from __future__ import annotations

import time
import xml.etree.ElementTree as et
from pathlib import Path
from typing import Any

try:
    import uiautomator2 as u2
except Exception:  # pragma: no cover - optional until runtime
    u2 = None


class UiAutomatorAdapter:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._device = None

    @property
    def device(self):
        if u2 is None:
            raise RuntimeError("uiautomator2 is not available in this environment")
        if self._device is None:
            self._device = u2.connect(self.serial)
        return self._device

    def app_start(self, package_name: str) -> None:
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

    def dump_nodes(self) -> list[dict[str, Any]]:
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
            }
            if item["text"] or item["content_desc"] or item["resource_id"]:
                nodes.append(item)
        return nodes

    def swipe_up(self) -> None:
        self.device.swipe_ext("up", scale=0.8)
        time.sleep(1)

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.device.screenshot(str(path))
        return path
