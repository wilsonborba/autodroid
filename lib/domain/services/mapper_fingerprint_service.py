from __future__ import annotations

import hashlib
from typing import Any


class MapperFingerprintService:
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

    @staticmethod
    def _normalize(value: Any) -> str:
        return str(value or "").strip().lower()
