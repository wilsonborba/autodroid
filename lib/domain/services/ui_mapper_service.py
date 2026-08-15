from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.core.utils.clock import utc_now
from lib.dal.local.database import session_scope
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter
from lib.domain.models.mapper_model import MapperSession
from lib.domain.models.mapper_types import MapperActionSafety, MapperLimits, MapperRunConfig, MapperSessionStatus
from lib.domain.services.mapper_engine import MapperEngine
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_mode_service import MapperModeService
from lib.domain.services.mapper_safety_service import MapperSafetyService
from lib.domain.services.navigation_context_service import NavigationContextService


@dataclass
class MapperActionCandidate:
    action_key: str
    label: str | None
    bounds: str | None
    node: dict[str, Any]
    node_key: str


class UiMapperService(MapperEngine):
    """Explores an app's UI and persists the discovered screens/actions/transitions.

    Exploration is checkpointed per session via `MapperScreen.expanded` (has this screen's
    candidates already been tried?) and `MapperSession.explored_up_to_depth` (how deep has the
    session been fully explored?). This lets a session be extended later (`complement`, issue
    #20) to a deeper mode, or resumed after a crash, without duplicating already-known data or
    re-navigating past what's already known: a known-but-unexpanded screen is expanded for the
    first time; a known-and-expanded screen is only re-walked (via its already-successful
    actions) to reach unexplored children below it, never re-classified.

    Traversal is still depth-first at the physical-click level (iterative deepening, not a
    literal breadth-first frontier with path replay): the device has no way to "teleport" to a
    mid-tree screen, reaching one always means physically clicking through from the app's root,
    which is exactly what DFS-with-backtrack already does naturally. Raising `max_depth` and
    re-running the same traversal is functionally equivalent to BFS-by-layer for the purpose of
    the checkpoint (`explored_up_to_depth`), without the complexity of maintaining a separate
    frontier/path-replay structure.
    """

    def __init__(self, settings: Settings) -> None:
        self.logger = get_logger(__name__)
        self.settings = settings
        self.adb = AdbAdapter(settings.android_serial)
        self.ui = UiAutomatorAdapter(settings.android_serial)
        self.navigation_context = NavigationContextService(self.adb)
        self.mode_service = MapperModeService()
        self.fingerprint_service = MapperFingerprintService()
        self.safety_service = MapperSafetyService()

    def run(self, config: MapperRunConfig) -> dict[str, Any]:
        if config.override and config.complement:
            raise ValueError("override and complement cannot both be set")

        limits = self.mode_service.get_limits(config.mode)

        if not config.override:
            with session_scope() as session:
                repository = SqlAlchemyMapperRepository(session)

                resumable = repository.get_resumable_session(config.package_name)
                if resumable is not None:
                    target_max_depth = max(resumable.max_depth, limits.max_depth)
                    self.logger.info(
                        "Resuming interrupted mapper session %s for %s up to depth %s",
                        resumable.id, config.package_name, target_max_depth,
                    )
                    return self._continue_session(repository, resumable, target_max_depth=target_max_depth, limits=limits, config=config, fresh=False)

                existing = repository.get_latest_session(config.package_name, status=MapperSessionStatus.COMPLETED)
                if existing is not None:
                    if not config.complement:
                        self.logger.info("Reusing mapper session %s for %s (override=False)", existing.id, config.package_name)
                        result = self._reused_session_result(existing)
                        result["complemented"] = False
                        return result
                    if existing.explored_up_to_depth >= limits.max_depth:
                        self.logger.info("Session %s already satisfies %s, complement is a no-op", existing.id, config.mode.value)
                        result = self._reused_session_result(existing)
                        result["complemented"] = False
                        return result
                    self.logger.info(
                        "Complementing mapper session %s for %s up to depth %s",
                        existing.id, config.package_name, limits.max_depth,
                    )
                    return self._continue_session(repository, existing, target_max_depth=limits.max_depth, limits=limits, config=config, fresh=False)

        self.logger.info("Starting mapper for %s in %s mode", config.package_name, config.mode.value)
        self.navigation_context.prepare_fresh_app_launch(config.package_name)

        with session_scope() as session:
            repository = SqlAlchemyMapperRepository(session)
            mapper_session = repository.create_session(
                package_name=config.package_name,
                mode=config.mode,
                skip_dangerous_actions=config.skip_dangerous_actions,
                max_depth=limits.max_depth,
                max_actions=limits.max_actions,
                max_scrolls=limits.max_scrolls,
                max_consecutive_empty_scrolls=limits.max_consecutive_empty_scrolls,
                metadata_json={"mode": config.mode.value},
            )
            mapper_session.status = MapperSessionStatus.RUNNING
            mapper_session.started_at = utc_now()
            repository.session.commit()  # the session row itself must survive a crash, not just its data (issue #25)
            return self._continue_session(repository, mapper_session, target_max_depth=limits.max_depth, limits=limits, config=config, fresh=True)

    def _continue_session(
        self,
        repository: SqlAlchemyMapperRepository,
        mapper_session: MapperSession,
        *,
        target_max_depth: int,
        limits: MapperLimits,
        config: MapperRunConfig,
        fresh: bool,
    ) -> dict[str, Any]:
        if not fresh:
            self.navigation_context.prepare_fresh_app_launch(config.package_name)
            mapper_session.status = MapperSessionStatus.RUNNING
            mapper_session.mode = config.mode
            mapper_session.max_depth = target_max_depth
            mapper_session.max_actions = max(mapper_session.max_actions, limits.max_actions)
            mapper_session.max_scrolls = max(mapper_session.max_scrolls, limits.max_scrolls)
            mapper_session.max_consecutive_empty_scrolls = max(mapper_session.max_consecutive_empty_scrolls, limits.max_consecutive_empty_scrolls)
            repository.session.commit()

        state = self._load_state(repository, mapper_session.id)
        visited_this_pass: set[int] = set()
        self._explore(
            repository,
            mapper_session.id,
            depth=0,
            state=state,
            visited_this_pass=visited_this_pass,
            max_depth=target_max_depth,
            max_actions=mapper_session.max_actions,
            max_scrolls=mapper_session.max_scrolls,
            max_consecutive_empty_scrolls=mapper_session.max_consecutive_empty_scrolls,
            config_skip_dangerous_actions=config.skip_dangerous_actions,
            package_name=config.package_name,
        )

        mapper_session.status = MapperSessionStatus.COMPLETED
        mapper_session.finished_at = utc_now()
        mapper_session.explored_up_to_depth = target_max_depth
        repository.session.commit()
        self.logger.info(
            "Completed mapper session %s for %s (explored_up_to_depth=%s)",
            mapper_session.id, mapper_session.package_name, target_max_depth,
        )
        return {
            "session_id": mapper_session.id,
            "package_name": mapper_session.package_name,
            "mode": mapper_session.mode.value,
            "screens_recorded": state["screens_recorded"],
            "actions_executed": state["actions_executed"],
            "scrolls_used": state["scrolls_used"],
            "revisited_screens": state["revisited_screens"],
            "status": mapper_session.status.value,
            "reused": False,
            "complemented": not fresh,
        }

    @staticmethod
    def _load_state(repository: SqlAlchemyMapperRepository, session_id: int) -> dict[str, int]:
        screens = repository.list_screens(session_id)
        actions = repository.list_actions(session_id)
        return {
            "screens_recorded": len(screens),
            "actions_executed": sum(1 for action in actions if action.executed),
            "scrolls_used": 0,
            "revisited_screens": sum(1 for screen in screens if screen.visit_count > 1),
        }

    @staticmethod
    def _reused_session_result(mapper_session: MapperSession) -> dict[str, Any]:
        return {
            "session_id": mapper_session.id,
            "package_name": mapper_session.package_name,
            "mode": mapper_session.mode.value,
            "screens_recorded": len(mapper_session.screens),
            "actions_executed": sum(1 for action in mapper_session.actions if action.executed),
            "scrolls_used": 0,
            "revisited_screens": sum(1 for screen in mapper_session.screens if screen.visit_count > 1),
            "status": mapper_session.status.value,
            "reused": True,
        }

    def _explore(
        self,
        repository: SqlAlchemyMapperRepository,
        session_id: int,
        *,
        depth: int,
        state: dict[str, int],
        visited_this_pass: set[int],
        max_depth: int,
        max_actions: int,
        max_scrolls: int,
        max_consecutive_empty_scrolls: int,
        config_skip_dangerous_actions: bool,
        package_name: str,
        ancestor_bounds: list[str] | None = None,
        peek_only: bool = False,
    ) -> int | None:
        ancestor_bounds = ancestor_bounds if ancestor_bounds is not None else []
        nodes = self.ui.dump_nodes()

        if self._left_target_app(nodes, package_name):
            return None

        fingerprint = self.fingerprint_service.fingerprint(nodes)
        structural_signature = self.fingerprint_service.structural_signature(nodes)
        existing_screen = repository.find_screen_by_fingerprint(session_id, fingerprint)

        if existing_screen is not None:
            repository.increment_screen_visit_count(existing_screen.id)
            state["revisited_screens"] += 1
            screen = existing_screen
            repository.session.commit()
            if screen.id in visited_this_pass:
                # cycle within this same traversal pass (e.g. an in-app back button): already
                # being handled higher up this same call stack, stop here to avoid recursing forever
                return screen.id
            visited_this_pass.add(screen.id)
            persisted_nodes = repository.get_screen(screen.id).nodes
            node_id_by_key = {node.node_key: node.id for node in persisted_nodes}
            self.logger.debug("Revisiting known screen %s at depth %s (visit_count=%s, expanded=%s)", screen.id, depth, screen.visit_count, existing_screen.expanded)

            if peek_only or depth >= max_depth:
                self.logger.debug("Not expanding screen %s: %s", screen.id, "peek_only" if peek_only else f"depth {depth} reached max_depth {max_depth}")
                return screen.id

            if existing_screen.expanded:
                # already fully processed in an earlier pass; only re-walk into it (via its own
                # already-successful actions) to reach children that might still need expanding
                for action in repository.list_actions(session_id, screen_id=screen.id, executed=True):
                    node = self._replay_target(repository, action)
                    if node is None or not node.bounds:
                        continue
                    if self.ui.click_bounds(node.bounds):
                        replay_to_screen_id = self._explore(repository, session_id, depth=depth + 1, state=state, visited_this_pass=visited_this_pass, max_depth=max_depth, max_actions=max_actions, max_scrolls=0, max_consecutive_empty_scrolls=max_consecutive_empty_scrolls, config_skip_dangerous_actions=config_skip_dangerous_actions, package_name=package_name, ancestor_bounds=ancestor_bounds + [node.bounds])
                        self._return_to_screen(package_name, ancestor_bounds, departed=replay_to_screen_id is None)
                return screen.id

            # resumed mid-screen (crash, a session continued in a deeper mode, or a forced
            # remap, issue #41): a pre-existing successful action might still be worth
            # replaying to reach a still-unexplored child (replay_known=True), and this also
            # scrolls for potentially new content exactly like a brand-new screen would, not
            # just whatever was captured before this pass started
            self._scroll_and_interact(
                repository, session_id, screen, nodes, node_id_by_key,
                depth=depth, state=state, visited_this_pass=visited_this_pass, max_depth=max_depth,
                max_actions=max_actions, max_scrolls=max_scrolls, max_consecutive_empty_scrolls=max_consecutive_empty_scrolls,
                config_skip_dangerous_actions=config_skip_dangerous_actions, package_name=package_name,
                ancestor_bounds=ancestor_bounds, replay_known=True,
            )
            return screen.id

        screen = repository.create_screen(
            session_id=session_id,
            fingerprint=fingerprint,
            structural_signature=structural_signature,
            screen_key=f"screen-{state['screens_recorded'] + 1}",
            depth=depth,
            ordinal=state["screens_recorded"],
            metadata_json={"node_count": len(nodes)},
        )
        state["screens_recorded"] += 1
        node_id_by_key = {}
        for index, node in enumerate(nodes):
            key = self._node_key(node, index)
            persisted = repository.create_node(
                screen_id=screen.id, node_key=key, text=node.get("text"), content_desc=node.get("content_desc"),
                resource_id=node.get("resource_id"), class_name=node.get("class_name"), bounds=node.get("bounds"),
                clickable=bool(node.get("clickable", False)), enabled=bool(node.get("enabled", True)),
                checkable=bool(node.get("checkable", False)), checked=bool(node.get("checked", False)),
                focusable=bool(node.get("focusable", False)), scrollable=bool(node.get("scrollable", False)),
                long_clickable=bool(node.get("long_clickable", False)), package_name=node.get("package_name"),
            )
            node_id_by_key[key] = persisted.id
        # commit as soon as a screen and its nodes exist (issue #25): a crash right after
        # this point still leaves this screen durable and resumable, not lost with everything
        # else in one giant uncommitted transaction
        repository.session.commit()
        visited_this_pass.add(screen.id)
        self.logger.debug("Created screen %s at depth %s (fingerprint=%s, %s node(s) persisted)", screen.id, depth, fingerprint[:12], len(nodes))

        if peek_only:
            # catalogued (screen + nodes already persisted above), never explored further:
            # opening "Message" reveals a compose screen, that's not an invitation to also
            # try clicking Send inside it (issue #31)
            return screen.id

        if repository.has_other_screen_with_structural_signature(session_id, structural_signature, exclude_screen_id=screen.id):
            # another screen of this same type (e.g. yet another person's profile page) is
            # already known in this session: recorded for coverage, but not explored again,
            # this is what stops a profile -> connections -> profile -> connections chain
            # after the second instance instead of after however deep it happens to go (#30)
            self.logger.info("Screen %s is another instance of an already-known structural type, not re-exploring it", screen.id)
            repository.mark_screen_expanded(screen.id)
            repository.session.commit()
            return screen.id

        # scroll and interact interleaved (issue #34): try whatever's already known after every
        # scroll, instead of scrolling all the way first and only then clicking anything. A mixed
        # feed (posts, ads, suggestions, ...) rarely repeats its exact viewport, so waiting for
        # that to decide "enough scrolling" (the old approach, #30) usually just burned through
        # the whole safety ceiling for no reason; stopping as soon as a scroll finds nothing new
        # is a far more reliable signal, `max_scrolls` stays the hard ceiling behind it either way
        self._scroll_and_interact(
            repository, session_id, screen, nodes, node_id_by_key,
            depth=depth, state=state, visited_this_pass=visited_this_pass, max_depth=max_depth,
            max_actions=max_actions, max_scrolls=max_scrolls, max_consecutive_empty_scrolls=max_consecutive_empty_scrolls,
            config_skip_dangerous_actions=config_skip_dangerous_actions, package_name=package_name,
            ancestor_bounds=ancestor_bounds, replay_known=False,
        )

        return screen.id

    def _scroll_and_interact(
        self,
        repository: SqlAlchemyMapperRepository,
        session_id: int,
        screen: Any,
        nodes: list[dict[str, Any]],
        node_id_by_key: dict[str, int],
        *,
        depth: int,
        state: dict[str, int],
        visited_this_pass: set[int],
        max_depth: int,
        max_actions: int,
        max_scrolls: int,
        max_consecutive_empty_scrolls: int,
        config_skip_dangerous_actions: bool,
        package_name: str,
        ancestor_bounds: list[str],
        replay_known: bool,
    ) -> None:
        """Shared by a brand-new screen and an existing-but-not-yet-expanded one (crash resume,
        a deeper complement, or a forced remap, issue #41): scroll and interact interleaved,
        candidates tried right after every scroll instead of only once scrolling is done."""
        accumulated_nodes = list(nodes)
        seen_keys = set(node_id_by_key)
        current_nodes = nodes
        consecutive_empty_scrolls = 0
        screen_scrolls_used = 0

        while True:
            if depth < max_depth:
                candidates = self._extract_candidates(accumulated_nodes, package_name)
                self.logger.debug("Screen %s: %s candidate(s) extracted (%s accumulated node(s) so far)", screen.id, len(candidates), len(accumulated_nodes))
                self._process_candidates(
                    repository, session_id, screen, candidates, node_id_by_key,
                    depth=depth, state=state, visited_this_pass=visited_this_pass, max_depth=max_depth,
                    max_actions=max_actions, max_consecutive_empty_scrolls=max_consecutive_empty_scrolls,
                    config_skip_dangerous_actions=config_skip_dangerous_actions, package_name=package_name,
                    ancestor_bounds=ancestor_bounds, replay_known=replay_known,
                )

            can_scroll = (
                any(node.get("scrollable") for node in current_nodes)
                and max_scrolls > 0
                and screen_scrolls_used < max_scrolls
                and consecutive_empty_scrolls < max_consecutive_empty_scrolls
            )
            if not can_scroll:
                self.logger.debug(
                    "Stopping scroll on screen %s after %s scroll(s): %s", screen.id, screen_scrolls_used,
                    "no scrollable content" if not any(node.get("scrollable") for node in current_nodes)
                    else "max_scrolls reached" if screen_scrolls_used >= max_scrolls
                    else f"{consecutive_empty_scrolls} consecutive scroll(s) found nothing new",
                )
                break

            self.ui.swipe_up()
            screen_scrolls_used += 1
            state["scrolls_used"] += 1
            current_nodes = self.ui.dump_nodes()

            if self._left_target_app(current_nodes, package_name):
                self._return_to_screen(package_name, ancestor_bounds, departed=True)
                break

            new_nodes_found = False
            new_node_count = 0
            for index, node in enumerate(current_nodes):
                key = self._node_key(node, index)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                new_nodes_found = True
                new_node_count += 1
                accumulated_nodes.append(node)
                persisted = repository.create_node(
                    screen_id=screen.id, node_key=key, text=node.get("text"), content_desc=node.get("content_desc"),
                    resource_id=node.get("resource_id"), class_name=node.get("class_name"), bounds=node.get("bounds"),
                    clickable=bool(node.get("clickable", False)), enabled=bool(node.get("enabled", True)),
                    checkable=bool(node.get("checkable", False)), checked=bool(node.get("checked", False)),
                    focusable=bool(node.get("focusable", False)), scrollable=bool(node.get("scrollable", False)),
                    long_clickable=bool(node.get("long_clickable", False)), package_name=node.get("package_name"),
                )
                node_id_by_key[key] = persisted.id
            if new_nodes_found:
                repository.session.commit()
                self.logger.debug("Scroll %s on screen %s found %s new node(s), continuing", screen_scrolls_used, screen.id, new_node_count)
                consecutive_empty_scrolls = 0
            else:
                consecutive_empty_scrolls += 1
                self.logger.debug("Scroll %s on screen %s found nothing new (%s/%s consecutive)", screen_scrolls_used, screen.id, consecutive_empty_scrolls, max_consecutive_empty_scrolls)

        if depth < max_depth:
            repository.mark_screen_expanded(screen.id)
            repository.session.commit()

    def _process_candidates(
        self,
        repository: SqlAlchemyMapperRepository,
        session_id: int,
        screen: Any,
        candidates: list[MapperActionCandidate],
        node_id_by_key: dict[str, int],
        *,
        depth: int,
        state: dict[str, int],
        visited_this_pass: set[int],
        max_depth: int,
        max_actions: int,
        max_consecutive_empty_scrolls: int,
        config_skip_dangerous_actions: bool,
        package_name: str,
        ancestor_bounds: list[str],
        replay_known: bool = True,
    ) -> None:
        """Tries every not-yet-tried candidate: classify, click (or skip if dangerous/no bounds),
        recurse into whatever it reveals, come back. Shared between a resumed screen (called once
        with a fixed candidate list, `replay_known=True`: an action already on file might still
        be worth replaying to reach children that never got explored) and a brand-new one (called
        again after every scroll, with `candidates` growing each time, `replay_known=False`: an
        action found again here was tried by this very call moments ago, in an earlier round of
        the same continuous scroll, its outcome is already fully known and nothing changed about
        it, so it's always just skipped, never replayed, issue #34)."""
        for candidate in candidates:
            if state["actions_executed"] >= max_actions:
                break
            node_id = node_id_by_key.get(candidate.node_key)

            existing_action = repository.find_action_by_key(session_id, screen.id, candidate.action_key)
            if existing_action is not None:
                if not replay_known:
                    self.logger.debug("Skipping %r on screen %s: already tried earlier this same scroll pass", candidate.label, screen.id)
                    continue
                existing_node = self._replay_target(repository, existing_action)
                if existing_node is not None and existing_node.bounds:
                    self.logger.debug("Replaying known action %r on screen %s", candidate.label, screen.id)
                    if self.ui.click_bounds(existing_node.bounds):
                        replay_to_screen_id = self._explore(repository, session_id, depth=depth + 1, state=state, visited_this_pass=visited_this_pass, max_depth=max_depth, max_actions=max_actions, max_scrolls=0, max_consecutive_empty_scrolls=max_consecutive_empty_scrolls, config_skip_dangerous_actions=config_skip_dangerous_actions, package_name=package_name, ancestor_bounds=ancestor_bounds + [existing_node.bounds])
                        self._return_to_screen(package_name, ancestor_bounds, departed=replay_to_screen_id is None)
                continue

            safety = self.safety_service.classify(candidate.node, candidate.label)
            self.logger.debug("Candidate found: %r (bounds=%s, safety=%s)", candidate.label, candidate.bounds, safety.value)
            action = repository.create_action(
                session_id=session_id,
                screen_id=screen.id,
                node_id=node_id,
                action_key=candidate.action_key,
                action_type="click",
                label=candidate.label,
                safety=safety,
                executed=False,
            )
            if safety == MapperActionSafety.DANGEROUS and config_skip_dangerous_actions:
                self.logger.warning("Blocked dangerous action %r on screen %s", candidate.label, screen.id)
                action.skipped_reason = "dangerous_action_blocked"
                repository.create_transition(
                    session_id=session_id,
                    from_screen_id=screen.id,
                    action_id=action.id,
                    to_screen_id=None,
                    result_type="skipped_dangerous",
                )
                repository.session.commit()
                continue
            if not candidate.bounds:
                self.logger.debug("Skipping candidate %r on screen %s: no bounds to click", candidate.label, screen.id)
                action.skipped_reason = "missing_bounds"
                repository.session.commit()
                continue
            success = self.ui.click_bounds(candidate.bounds)
            action.executed = True
            action.success = success
            state["actions_executed"] += 1
            self.logger.debug("Clicked %r (bounds=%s) -> success=%s", candidate.label, candidate.bounds, success)
            if success:
                # reveals a sub-interface without necessarily doing anything itself ("Message"
                # opens a compose screen, it doesn't send one): catalog what it reveals, never
                # click anything inside it (issue #31)
                peek = self.safety_service.is_peek_candidate(candidate.node, candidate.label)
                if peek:
                    self.logger.debug("Candidate %r is a peek target: cataloguing whatever it reveals without exploring further", candidate.label)
                to_screen_id = self._explore(repository, session_id, depth=depth + 1, state=state, visited_this_pass=visited_this_pass, max_depth=max_depth, max_actions=max_actions, max_scrolls=0, max_consecutive_empty_scrolls=max_consecutive_empty_scrolls, config_skip_dangerous_actions=config_skip_dangerous_actions, package_name=package_name, ancestor_bounds=ancestor_bounds + [candidate.bounds], peek_only=peek)
                repository.create_transition(
                    session_id=session_id,
                    from_screen_id=screen.id,
                    action_id=action.id,
                    to_screen_id=to_screen_id,
                    result_type="clicked" if to_screen_id is not None else "left_app",
                )
                self._return_to_screen(package_name, ancestor_bounds, departed=to_screen_id is None)
            else:
                repository.create_transition(
                    session_id=session_id,
                    from_screen_id=screen.id,
                    action_id=action.id,
                    to_screen_id=None,
                    result_type="failed_click",
                )
            # commit per action (issue #25): whatever already ran is durable before moving on,
            # a crash mid-mapping only ever loses the one action currently in flight
            repository.session.commit()

    def _left_target_app(self, nodes: list[dict[str, Any]], package_name: str) -> bool:
        # a click (or a scroll) can legitimately leave the target app (share sheet, external
        # link, sign-in with Google, file picker, ...): none of that is "dangerous" by
        # MapperSafetyService's keyword check, so it's caught here instead. Only trust this when
        # at least one node actually reports a package (uiautomator dumps normally do), otherwise
        # there's nothing to compare and exploration proceeds as before (issue #27).
        observed_packages = {node.get("package_name") for node in nodes if node.get("package_name")}
        if observed_packages and package_name not in observed_packages:
            self.logger.warning(
                "Mapper left %s (observed %s instead), backing off without recording this screen",
                package_name, sorted(observed_packages),
            )
            return True
        return False

    def _replay_target(self, repository: SqlAlchemyMapperRepository, action: Any) -> Any | None:
        """An already-recorded action is only worth replaying if it's known to lead somewhere
        still worth reaching: a real destination screen that isn't already fully explored. A
        click that failed, left the app, or leads to a screen that's already expanded just
        wastes a round trip re-doing work that's either useless or already done, and every time
        the current screen gets revisited, ALL of its recorded actions used to be replayed
        unconditionally, including these dead ends, over and over. This is what a user reported
        as an endless loop (issue #33)."""
        if not action.success or action.node_id is None:
            self.logger.debug("Action %s (%r) not replayable: %s", action.id, action.label, "never clicked successfully" if not action.success else "no source node on file")
            return None
        transition = repository.find_transition_by_action(action.id)
        if transition is None or transition.to_screen_id is None:
            self.logger.debug("Action %s (%r) not replayable: led nowhere recorded (dead end)", action.id, action.label)
            return None
        destination = repository.get_screen(transition.to_screen_id)
        if destination is not None and destination.expanded:
            self.logger.debug("Action %s (%r) not replayable: destination screen %s is already fully expanded", action.id, action.label, destination.id)
            return None
        return repository.get_node(action.node_id)

    BACK_LABELS = {"back", "navigate up", "go back", "up", "close"}
    BACK_RESOURCE_ID_HINTS = ("back_button", "btn_back", "toolbar_back", "nav_back", "back_arrow", ":id/back")

    def _find_back_affordance(self, nodes: list[dict[str, Any]], package_name: str) -> dict[str, Any] | None:
        for node in nodes:
            if not node.get("clickable") or not node.get("bounds"):
                continue
            node_package = node.get("package_name")
            if node_package is not None and node_package != package_name:
                continue
            label = str(node.get("content_desc") or node.get("text") or "").strip().lower()
            resource_id = str(node.get("resource_id") or "").lower()
            if label in self.BACK_LABELS or any(hint in resource_id for hint in self.BACK_RESOURCE_ID_HINTS):
                return node
        return None

    def _navigate_back(self, package_name: str) -> None:
        """The system back button is context-dependent and not always safe during exploration:
        pressed from the app's own root it can exit to the home screen or a previous app instead
        of just closing the current screen, silently taking the Mapper out of the target app.
        An in-app back/up/close affordance, when the current screen has one, does what we
        actually mean ("undo this last navigation") without that risk; the system back button is
        only used when no such affordance is found."""
        nodes = self.ui.dump_nodes()
        back_node = self._find_back_affordance(nodes, package_name)
        if back_node is not None:
            self.logger.debug("Navigating back via in-app affordance %r", back_node.get("content_desc") or back_node.get("text"))
            self.ui.click_bounds(back_node["bounds"])
        else:
            self.logger.debug("Navigating back via the system back button: no in-app back/up/close affordance found")
            self.adb.press_back()

    def _return_to_screen(self, package_name: str, ancestor_bounds: list[str], *, departed: bool) -> None:
        """Undoes the click that was just made, one way or another, so the caller's own screen
        is current again and its remaining candidates can keep being tried.

        A normal in-app click just needs `_navigate_back` (issue #27). A click that left the
        target app is a different, harder problem: from an unknown foreign screen there's no
        reliable "undo", pressing back again can just as easily open a third app or exit further
        (the exact failure a user reported: once it left the app once, it never found its way
        back, and each of its own saved actions afterward kept opening a different app off the
        home screen). The only reliable recovery is to relaunch the target app fresh (guaranteed
        known state: its root) and replay the exact clicks that got here (issue #28), passed down
        the recursion as `ancestor_bounds` rather than looked up in the database: the transition
        connecting into the current screen isn't committed yet while we're still inside exploring
        it, so a lookup at this point wouldn't find it."""
        if not departed:
            self._navigate_back(package_name)
            return
        self.logger.warning("Relaunching %s and replaying %s step(s) back to the current screen after leaving the app", package_name, len(ancestor_bounds))
        self.navigation_context.prepare_fresh_app_launch(package_name)
        for bounds in ancestor_bounds:
            self.ui.click_bounds(bounds)

    def _extract_candidates(self, nodes: list[dict[str, Any]], package_name: str) -> list[MapperActionCandidate]:
        # clickable="false" is not trusted on its own (issue #37): LinkedIn (and apparently other
        # apps) regularly exports genuinely tappable elements that way, class doesn't matter
        # either, a plain TextView ("Groups") turned out just as tappable as a real Button. The
        # actual gate against wasting a click on this stays the safety classification below (an
        # attempt that does nothing is harmless, dedup notices the screen didn't change), not
        # this accessibility flag the app itself doesn't always report correctly.
        #
        # a real, announced label is required to trust a non-clickable node though: without that,
        # this would also catch every plain structural container (a ScrollView/RecyclerView/
        # FrameLayout almost always carries a resource_id but no text of its own), a resource_id
        # alone was only ever a weak fallback for an icon-only *clickable* button. A scrollable
        # container is excluded either way, that's a region to scroll, not a thing to tap.
        candidates: list[MapperActionCandidate] = []
        for index, node in enumerate(nodes):
            label = str(node.get("text") or node.get("content_desc") or "").strip() or None
            if not node.get("clickable") and not label:
                continue
            if not label and not node.get("resource_id"):
                continue
            if node.get("scrollable"):
                continue
            # a dump includes whatever else is on screen too (status bar, nav bar, launcher
            # edges), each carrying its own package_name: clicking those wastes the action
            # budget and leaves the app before ever trying the target app's own buttons (issue
            # #27). Unset package_name is allowed through (unknown, not necessarily foreign).
            node_package = node.get("package_name")
            if node_package is not None and node_package != package_name:
                continue
            candidates.append(
                MapperActionCandidate(
                    action_key=f"click:{index}:{node.get('resource_id') or label or node.get('bounds')}",
                    label=label,
                    bounds=node.get("bounds"),
                    node=node,
                    node_key=self._node_key(node, index),
                )
            )
        return candidates

    def _node_key(self, node: dict[str, Any], index: int) -> str:
        return f"{index}:{node.get('resource_id') or ''}:{node.get('text') or ''}:{node.get('content_desc') or ''}:{node.get('bounds') or ''}"
