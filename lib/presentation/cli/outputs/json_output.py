from __future__ import annotations

import json
from typing import Any


class JsonOutput:
    @staticmethod
    def render(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
