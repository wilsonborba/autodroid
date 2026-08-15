from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    app_name: str
    debug: bool
    database_url: str
    worker_name: str
    queue_poll_interval_seconds: float
    output_dir: Path
    log_file: Path
    app_timezone: str
    android_serial: str
    linkedin_package_name: str
    ocr_language: str
    mapper_auto_remap_enabled: bool
    mapper_auto_remap_threshold: int

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)



def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("AUTODROID_APP_NAME", "autodroid"),
        debug=os.getenv("AUTODROID_DEBUG", "false").lower() == "true",
        database_url=os.getenv("AUTODROID_DATABASE_URL", "sqlite:///./var/autodroid.db"),
        worker_name=os.getenv("AUTODROID_WORKER_NAME", "main"),
        queue_poll_interval_seconds=float(os.getenv("AUTODROID_QUEUE_POLL_INTERVAL_SECONDS", "2.0")),
        output_dir=Path(os.getenv("AUTODROID_OUTPUT_DIR", "output")),
        log_file=Path(os.getenv("AUTODROID_LOG_FILE", "var/logs/autodroid.log")),
        app_timezone=os.getenv("AUTODROID_TIMEZONE", "UTC"),
        android_serial=os.getenv("ANDROID_SERIAL", "127.0.0.1:5555"),
        linkedin_package_name=os.getenv("LINKEDIN_PACKAGE_NAME", "com.linkedin.android"),
        ocr_language=os.getenv("AUTODROID_OCR_LANGUAGE", "en"),
        mapper_auto_remap_enabled=os.getenv("AUTODROID_MAPPER_AUTO_REMAP_ENABLED", "false").lower() == "true",
        mapper_auto_remap_threshold=int(os.getenv("AUTODROID_MAPPER_AUTO_REMAP_THRESHOLD", "3")),
    )
