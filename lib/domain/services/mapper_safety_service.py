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

    def classify(self, node: dict[str, Any], label: str | None) -> MapperActionSafety:
        haystacks = [
            str(label or "").lower(),
            str(node.get("text") or "").lower(),
            str(node.get("content_desc") or "").lower(),
            str(node.get("resource_id") or "").lower(),
        ]
        merged = " ".join(haystacks)
        if any(pattern in merged for pattern in self.DANGEROUS_PATTERNS):
            return MapperActionSafety.DANGEROUS
        return MapperActionSafety.SAFE
