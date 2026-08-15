from __future__ import annotations

import hashlib
from typing import Any


class MapperFingerprintService:
    """`fingerprint()` is screen identity: it includes text/content_desc on purpose, because many
    Android screens reuse the same generic resource_id/class_name across genuinely different
    menus or list rows (a settings screen and a profile screen can share the exact same row
    layout, only the label text tells them apart). Stripping text there would make the Mapper
    confuse real, different screens.

    `structural_signature()` (issue #25) is a separate, narrower signature used only to detect
    when a scrolling screen (a feed) is showing "more of the same" rather than something new:
    it deliberately ignores text/content_desc/bounds, so two feed cards with different captions
    but the same layout are recognized as the same pattern."""

    def fingerprint(self, nodes: list[dict[str, Any]]) -> str:
        normalized = []
        for node in nodes[:200]:
            normalized.append(
                "|".join(
                    [
                        self._normalize(node.get("resource_id")),
                        self._normalize(node.get("text")),
                        self._normalize(node.get("content_desc")),
                        self._normalize(node.get("class_name")),
                        "1" if node.get("clickable") else "0",
                        "1" if node.get("scrollable") else "0",
                    ]
                )
            )
        normalized.sort()
        payload = "\n".join(normalized)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def equivalent(self, left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
        return self.fingerprint(left) == self.fingerprint(right)

    def structural_signature(self, nodes: list[dict[str, Any]]) -> str:
        normalized = []
        for node in nodes[:200]:
            normalized.append(
                "|".join(
                    [
                        self._normalize(node.get("resource_id")),
                        self._normalize(node.get("class_name")),
                        "1" if node.get("clickable") else "0",
                        "1" if node.get("scrollable") else "0",
                        "1" if node.get("checkable") else "0",
                        "1" if node.get("focusable") else "0",
                        "1" if node.get("long_clickable") else "0",
                    ]
                )
            )
        normalized.sort()
        payload = "\n".join(normalized)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize(value: Any) -> str:
        return str(value or "").strip().lower()
