from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from lib.core.settings import Settings
from lib.core.utils.json_utils import write_json
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.dal.remote.ocr_adapter import OcrAdapter
from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter
from lib.domain.services.navigation_context_service import NavigationContextService


class LinkedInAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adb = AdbAdapter(settings.android_serial)
        self.ui = UiAutomatorAdapter(settings.android_serial)
        self.ocr = OcrAdapter(settings.ocr_language)
        self.navigation_context = NavigationContextService(self.adb)

    def extract_profile_basic(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_device_ready()
        resume_context = self.navigation_context.load_resume_context(payload)
        if self.navigation_context.can_resume(resume_context):
            self.navigation_context.prepare_fresh_app_launch(self.settings.linkedin_package_name)
        else:
            self.navigation_context.prepare_fresh_app_launch(self.settings.linkedin_package_name)

        profile_opened = self._open_profile_entrypoint()

        scrolls = int(payload.get("scrolls", 2))
        screenshot_dir = self.settings.output_dir / "screenshots"
        all_nodes: list[dict[str, Any]] = []
        for index in range(scrolls + 1):
            all_nodes.extend(self.ui.dump_nodes())
            if index < scrolls:
                self.ui.swipe_up()

        deduped_nodes = list(OrderedDict((self._node_key(node), node) for node in all_nodes).values())
        visible_texts = self._collect_texts(deduped_nodes)
        ocr_lines: list[str] = []
        if not visible_texts:
            screenshot_path = self.ui.screenshot(screenshot_dir / "linkedin_profile_basic.png")
            ocr_lines = self.ocr.extract_lines(screenshot_path)

        result = {
            "profile_opened": profile_opened,
            "name": self._guess_name(visible_texts or ocr_lines),
            "headline": self._guess_headline(visible_texts or ocr_lines),
            "location": self._guess_location(visible_texts or ocr_lines),
            "current_company": self._guess_current_company(visible_texts or ocr_lines),
            "visible_texts": visible_texts,
            "ocr_lines": ocr_lines,
            "raw_nodes": deduped_nodes,
        }
        if payload.get("save_result_json"):
            output_path = Path(payload["save_result_json"])
            write_json(output_path, result)
        return result

    def _open_profile_entrypoint(self) -> bool:
        if self.ui.click_first_by_text_or_description(
            "Meu perfil",
            "Perfil",
            "My Profile",
            "View Profile",
            "Ver perfil",
        ):
            return True

        menu_opened = self.ui.click_first_by_text_or_description_contains(
            "access my profile",
            "my profile and communities",
            "profile and other navigation links",
        )
        if menu_opened and self.ui.click_first_by_text_or_description(
            "My Profile",
            "View Profile",
            "Meu perfil",
            "Ver perfil",
            "Profile",
        ):
            return True

        return False

    def _ensure_device_ready(self) -> None:
        if self.adb.get_state() != "device":
            raise RuntimeError("ADB device is not ready")
        if self.adb.shell("getprop sys.boot_completed") != "1":
            raise RuntimeError("Android worker has not finished booting")

    @staticmethod
    def _node_key(node: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(node.get("text", "")),
            str(node.get("content_desc", "")),
            str(node.get("resource_id", "")),
            str(node.get("bounds", "")),
        )

    @staticmethod
    def _collect_texts(nodes: list[dict[str, Any]]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for node in nodes:
            for key in ("text", "content_desc"):
                value = str(node.get(key, "")).strip()
                if value and value not in seen:
                    seen.add(value)
                    items.append(value)
        return items

    @staticmethod
    def _guess_name(lines: list[str]) -> str | None:
        ignored = {"LinkedIn", "Meu perfil", "Perfil", "Profile", "Me", "My Profile"}
        for line in lines[:12]:
            if line in ignored:
                continue
            if 4 <= len(line) <= 80 and len(line.split()) >= 2:
                return line
        return None

    @staticmethod
    def _guess_headline(lines: list[str]) -> str | None:
        keywords = ["engineer", "developer", "manager", "analyst", "designer", "founder", "specialist", " na ", " at "]
        for line in lines:
            lowered = line.lower()
            if any(keyword in lowered for keyword in keywords):
                return line
        return None

    @staticmethod
    def _guess_location(lines: list[str]) -> str | None:
        for line in lines:
            if "," in line and len(line) < 80:
                return line
        return None

    @staticmethod
    def _guess_current_company(lines: list[str]) -> str | None:
        company_markers = ["empresa", "works at", "current", "company", "trabalha"]
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in company_markers):
                return line
        return None
