from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.core.utils.json_utils import write_json
from lib.dal.local.database import session_scope
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.domain.models.mapper_flow_model import MapperFlowStep
from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService
from lib.domain.services.mapper_flow_service import MapperFlowService
from lib.domain.services.navigation_context_service import NavigationContextService

EXTRACT_PROFILE_FLOW_NAME = "extract_profile_basic"
PROFILE_SCREENSHOT_FILENAME = "linkedin_profile_basic.png"


class LinkedInAdapter:
    """Extracts basic LinkedIn profile data.

    Navigation to the profile entrypoint runs as a MapperFlow (see issue #18), auto-created
    on first use and reused afterwards, so it is decoupled from this class and inspectable via
    `mapper flow show`. Scroll/dump/OCR steps stay payload-driven here (their count depends on
    `payload["scrolls"]` per call) but still execute through MapperFlowExecutionService, so no
    click/scroll logic is duplicated between this adapter and the flow engine. Interpreting the
    collected text (name/headline/etc) is domain logic, not navigation, so it stays here.
    """

    def __init__(self, settings: Settings) -> None:
        self.logger = get_logger(__name__)
        self.settings = settings
        self.adb = AdbAdapter(settings.android_serial)
        self.navigation_context = NavigationContextService(self.adb)
        self.flow_execution_service = MapperFlowExecutionService(settings)

    def extract_profile_basic(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.logger.info("Starting LinkedIn profile extraction")
        self._ensure_device_ready()
        self.navigation_context.prepare_fresh_app_launch(self.settings.linkedin_package_name)

        entrypoint_step = self._ensure_entrypoint_step()
        entrypoint_result = self.flow_execution_service.run_step(entrypoint_step)
        profile_opened = bool(entrypoint_result.get("success"))

        scrolls = int(payload.get("scrolls", 2))
        all_nodes: list[dict[str, Any]] = []
        for index in range(scrolls + 1):
            dump_result = self.flow_execution_service.run_step(self._transient_step("dump_nodes"))
            all_nodes.extend(dump_result.get("nodes") or [])
            if index < scrolls:
                self.flow_execution_service.run_step(self._transient_step("scroll_down"))

        deduped_nodes = list(OrderedDict((self._node_key(node), node) for node in all_nodes).values())
        visible_texts = self._collect_texts(deduped_nodes)
        ocr_lines: list[str] = []
        if not visible_texts:
            self.flow_execution_service.run_step(self._transient_step("screenshot", params_json={"filename": PROFILE_SCREENSHOT_FILENAME}))
            ocr_result = self.flow_execution_service.run_step(self._transient_step("ocr_extract", params_json={"filename": PROFILE_SCREENSHOT_FILENAME}))
            ocr_lines = ocr_result.get("ocr_lines") or []

        self.logger.info("LinkedIn profile entrypoint opened=%s", profile_opened)
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

    def _ensure_entrypoint_step(self) -> MapperFlowStep:
        with session_scope() as session:
            service = MapperFlowService(session)
            flow = service.flow_repository.get_flow_by_name(self.settings.linkedin_package_name, EXTRACT_PROFILE_FLOW_NAME)
            if flow is None:
                self.logger.info("Creating mapper flow %s for %s", EXTRACT_PROFILE_FLOW_NAME, self.settings.linkedin_package_name)
                flow = service.create_flow(
                    name=EXTRACT_PROFILE_FLOW_NAME,
                    package_name=self.settings.linkedin_package_name,
                    description="Open the LinkedIn profile entrypoint, trying the direct shortcut first and falling back to the navigation menu.",
                    steps=[
                        {
                            "action_type": "click_first_match",
                            "selector": {
                                "attempts": [
                                    {"match": "exact", "candidates": ["Meu perfil", "Perfil", "My Profile", "View Profile", "Ver perfil"]},
                                    {
                                        "match": "contains_then_exact",
                                        "open_candidates": ["access my profile", "my profile and communities", "profile and other navigation links"],
                                        "then_candidates": ["My Profile", "View Profile", "Meu perfil", "Ver perfil", "Profile"],
                                    },
                                ]
                            },
                        }
                    ],
                )
            return service.flow_repository.ordered_steps(flow)[0]

    def _transient_step(self, action_type: str, *, selector_json: dict[str, Any] | None = None, params_json: dict[str, Any] | None = None) -> MapperFlowStep:
        """A step used for this call only, not persisted. Reuses the execution service's
        handlers (dump/scroll/screenshot/ocr) without requiring every extraction run to
        write a fixed, payload-independent step count into the flow definition."""
        step = MapperFlowStep(package_name=self.settings.linkedin_package_name, action_type=action_type, selector_json=selector_json or {}, params_json=params_json)
        step.id = 0
        return step

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
