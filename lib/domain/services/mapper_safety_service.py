from __future__ import annotations

from typing import Any

from lib.domain.models.mapper_types import MapperActionSafety


class MapperSafetyService:
    DANGEROUS_PATTERNS = (
        "delete",
        "remove",
        "logout",
        "log out",
        "sign out",
        "send",
        "post",
        "publish",
        "purchase",
        "buy",
        "pay",
        "apply",
        "submit",
        "archive",
        "discard",
    )

    # candidates known for revealing a sub-interface without necessarily doing anything by
    # themselves (issue #31): opening "Message" shows a compose screen, it doesn't send a
    # message. Clicking these is still allowed (they're not dangerous), but what they reveal is
    # only catalogued, never explored further, that's a separate concern from safety-to-click.
    PEEK_PATTERNS = (
        "message",
        "more options",
        "more actions",
        "options menu",
        "overflow",
    )

    def classify(self, node: dict[str, Any], label: str | None) -> MapperActionSafety:
        merged = self._haystack(node, label)
        if any(pattern in merged for pattern in self.DANGEROUS_PATTERNS):
            return MapperActionSafety.DANGEROUS
        return MapperActionSafety.SAFE

    def is_peek_candidate(self, node: dict[str, Any], label: str | None) -> bool:
        merged = self._haystack(node, label)
        return any(pattern in merged for pattern in self.PEEK_PATTERNS)

    @staticmethod
    def _haystack(node: dict[str, Any], label: str | None) -> str:
        return " ".join([
            str(label or "").lower(),
            str(node.get("text") or "").lower(),
            str(node.get("content_desc") or "").lower(),
            str(node.get("resource_id") or "").lower(),
        ])
