from __future__ import annotations

import re
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
        if self._matches_any(merged, self.DANGEROUS_PATTERNS):
            return MapperActionSafety.DANGEROUS
        return MapperActionSafety.SAFE

    def is_peek_candidate(self, node: dict[str, Any], label: str | None) -> bool:
        merged = self._haystack(node, label)
        return self._matches_any(merged, self.PEEK_PATTERNS)

    @staticmethod
    def _matches_any(haystack: str, patterns: tuple[str, ...]) -> bool:
        # whole-word matching, not a raw substring check (issue #36): "post" as a plain substring
        # also matched inside "posts", wrongly flagging LinkedIn's own top search bar ("Search for
        # people, jobs, posts, and more") as dangerous and blocking it every session
        return any(re.search(rf"\b{re.escape(pattern)}\b", haystack) for pattern in patterns)

    @staticmethod
    def _haystack(node: dict[str, Any], label: str | None) -> str:
        merged = " ".join([
            str(label or "").lower(),
            str(node.get("text") or "").lower(),
            str(node.get("content_desc") or "").lower(),
            str(node.get("resource_id") or "").lower(),
        ])
        # a resource_id is snake_case/dotted, not space-separated ("post_comment_button"); without
        # this, the underscore/dot/colon/slash joints count as part of the word for \b purposes and
        # a whole-word match would never fire inside one
        return re.sub(r"[_:/.\-]+", " ", merged)
