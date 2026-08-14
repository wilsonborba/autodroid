from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo



def utc_now() -> datetime:
    return datetime.now(timezone.utc)



def local_now(zone: ZoneInfo) -> datetime:
    return utc_now().astimezone(zone)
