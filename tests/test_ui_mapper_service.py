from __future__ import annotations

from lib.core.logs import get_logger
from lib.domain.models.mapper_types import MapperMode, MapperRunConfig
from lib.domain.services.ui_mapper_service import UiMapperService


class FakeAdb:
    def __init__(self) -> None:
        self.back_calls = 0

    def press_back(self) -> None:
        self.back_calls += 1


class FakeNav:
    def __init__(self) -> None:
        self.prepared = []

    def prepare_fresh_app_launch(self, package_name: str) -> None:
        self.prepared.append(package_name)


class FakeUi:
    def __init__(self) -> None:
        self.clicks = []
        self.swipes = 0
        self.dumps = [
            [
                {"text": "Profile", "content_desc": "", "resource_id": "profile", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True},
                {"text": "Static", "content_desc": "", "resource_id": "static", "class_name": "TextView", "bounds": "[0,10][10,20]", "clickable": False, "enabled": True},
            ],
            [
                {"text": "Profile Details", "content_desc": "", "resource_id": "profile_details", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": False, "enabled": True},
            ],
        ]

    def dump_nodes(self):
        return self.dumps.pop(0) if self.dumps else []

    def click_bounds(self, bounds: str) -> bool:
        self.clicks.append(bounds)
        return True

    def swipe_up(self) -> None:
        self.swipes += 1


class FakeRepo:
    def __init__(self) -> None:
        self.session_id = 1
        self.screen_id = 0
        self.fingerprints = {}
        self.action_id = 0
        self.sessions = []
        self.screens = []
        self.nodes = []
        self.actions = []
        self.transitions = []

    def create_session(self, **kwargs):
        session = type('Session', (), {'id': self.session_id, 'package_name': kwargs['package_name'], 'mode': kwargs['mode'], 'status': type('S', (), {'value': 'pending'})(), 'started_at': None, 'finished_at': None})()
        session.status = type('Status', (), {'value': 'pending'})()
        self.sessions.append(kwargs)
        self.created_session = session
        return session

    def create_screen(self, **kwargs):
        self.screen_id += 1
        screen = type('Screen', (), {'id': self.screen_id, 'visit_count': 1})()
        self.screens.append(kwargs)
        self.fingerprints[kwargs['fingerprint']] = screen
        return screen

    def find_screen_by_fingerprint(self, session_id: int, fingerprint: str):
        return self.fingerprints.get(fingerprint)

    def increment_screen_visit_count(self, screen_id: int):
        return type('Screen', (), {'id': screen_id, 'visit_count': 2})()

    def create_node(self, **kwargs):
        node = type('Node', (), {'id': len(self.nodes) + 1})()
        self.nodes.append(kwargs)
        return node

    def create_action(self, **kwargs):
        self.action_id += 1
        action = type('Action', (), {'id': self.action_id, 'executed': False, 'success': None, 'skipped_reason': None})()
        self.actions.append(kwargs)
        return action

    def create_transition(self, **kwargs):
        self.transitions.append(kwargs)
        return kwargs


class FakeSessionScope:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_ui_mapper_service_runs_light_mode_with_basic_capture(monkeypatch) -> None:
    service = UiMapperService.__new__(UiMapperService)
    service.logger = get_logger(__name__)
    service.settings = None
    service.adb = FakeAdb()
    service.ui = FakeUi()
    service.navigation_context = FakeNav()
    from lib.domain.services.mapper_mode_service import MapperModeService
    from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
    service.mode_service = MapperModeService()
    service.fingerprint_service = MapperFingerprintService()
    from lib.domain.services.mapper_safety_service import MapperSafetyService
    service.safety_service = MapperSafetyService()

    fake_repo = FakeRepo()
    monkeypatch.setattr('lib.domain.services.ui_mapper_service.session_scope', lambda: FakeSessionScope())
    monkeypatch.setattr('lib.domain.services.ui_mapper_service.SqlAlchemyMapperRepository', lambda session: fake_repo)

    result = UiMapperService.run(service, MapperRunConfig(package_name='com.linkedin.android', mode=MapperMode.LIGHT))

    assert result['package_name'] == 'com.linkedin.android'
    assert result['actions_executed'] == 1
    assert result['revisited_screens'] >= 0
    assert len(fake_repo.screens) >= 1
    assert service.navigation_context.prepared == ['com.linkedin.android']


def test_ui_mapper_service_skips_dangerous_actions(monkeypatch) -> None:
    service = UiMapperService.__new__(UiMapperService)
    service.logger = get_logger(__name__)
    service.settings = None
    service.adb = FakeAdb()

    class DangerousUi(FakeUi):
        def __init__(self) -> None:
            super().__init__()
            self.dumps = [[{"text": "Delete", "content_desc": "", "resource_id": "delete_account", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True}]]

    service.ui = DangerousUi()
    service.navigation_context = FakeNav()
    from lib.domain.services.mapper_mode_service import MapperModeService
    from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
    from lib.domain.services.mapper_safety_service import MapperSafetyService
    service.mode_service = MapperModeService()
    service.fingerprint_service = MapperFingerprintService()
    service.safety_service = MapperSafetyService()

    fake_repo = FakeRepo()
    monkeypatch.setattr('lib.domain.services.ui_mapper_service.session_scope', lambda: FakeSessionScope())
    monkeypatch.setattr('lib.domain.services.ui_mapper_service.SqlAlchemyMapperRepository', lambda session: fake_repo)

    result = UiMapperService.run(service, MapperRunConfig(package_name='com.linkedin.android', mode=MapperMode.LIGHT, skip_dangerous_actions=True))

    assert result['actions_executed'] == 0
