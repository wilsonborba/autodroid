from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from lib.core.utils.clock import utc_now
from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.local.mapper_route_repository import SqlAlchemyMapperRoutePerformanceRepository
from lib.domain.models.mapper_model import MapperTransition
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode
from lib.domain.services.mapper_route_planner_service import (
    DIRECT_PATH,
    RESTART,
    CostEstimator,
    MapperRoutePlannerService,
    RestartOption,
    RouteCandidate,
    StrategySelector,
    direct_route_signature,
    restart_route_signature,
)


def make_transition(id: int, from_screen_id: int = 1, to_screen_id: int | None = 2) -> MapperTransition:
    transition = MapperTransition(session_id=1, from_screen_id=from_screen_id, action_id=id, to_screen_id=to_screen_id, result_type="clicked")
    transition.id = id
    return transition


def fake_perf(ewma_duration_ms: float, sample_count: int = 1) -> SimpleNamespace:
    return SimpleNamespace(ewma_duration_ms=ewma_duration_ms, sample_count=sample_count)


# --- CostEstimator ---------------------------------------------------------

def test_cost_estimator_uses_ewma_for_known_edges() -> None:
    estimator = CostEstimator(default_transition_cost_ms=1000, unknown_edge_penalty_ms=500)
    route = [make_transition(1), make_transition(2)]
    performance = {1: fake_perf(300), 2: fake_perf(700)}

    assert estimator.estimate_route(route, performance) == 1000  # no unknowns, no penalty


def test_cost_estimator_uses_default_and_penalty_for_unknown_edges() -> None:
    estimator = CostEstimator(default_transition_cost_ms=1000, unknown_edge_penalty_ms=500)
    route = [make_transition(1), make_transition(2)]

    assert estimator.estimate_route(route, {}) == 2000 + 1000  # 2 * (1000 default + 500 penalty)


def test_cost_estimator_mixes_known_and_unknown_edges() -> None:
    estimator = CostEstimator(default_transition_cost_ms=1000, unknown_edge_penalty_ms=500)
    route = [make_transition(1), make_transition(2)]
    performance = {1: fake_perf(300)}

    # known: 300. unknown: 1000 default + 500 penalty
    assert estimator.estimate_route(route, performance) == 300 + 1500


def test_cost_estimator_reliability_penalty_is_noop_with_no_samples() -> None:
    estimator = CostEstimator(reliability_penalty_weight=1.0)
    assert estimator.apply_reliability_penalty(1000.0, success_count=0, failure_count=0) == 1000.0


def test_cost_estimator_reliability_penalty_scales_with_failure_rate() -> None:
    estimator = CostEstimator(reliability_penalty_weight=1.0)

    all_success = estimator.apply_reliability_penalty(1000.0, success_count=10, failure_count=0)
    half_failure = estimator.apply_reliability_penalty(1000.0, success_count=5, failure_count=5)
    all_failure = estimator.apply_reliability_penalty(1000.0, success_count=0, failure_count=10)

    assert all_success == 1000.0
    assert half_failure == 1500.0
    assert all_failure == 2000.0


def test_cost_estimator_weight_fn_prefers_ewma_over_default() -> None:
    estimator = CostEstimator(default_transition_cost_ms=1000)
    weight_fn = estimator.weight_fn({1: fake_perf(42)})

    assert weight_fn(make_transition(1)) == 42
    assert weight_fn(make_transition(2)) == 1000


# --- route/restart signatures ------------------------------------------------

def test_direct_route_signature_reflects_exact_sequence() -> None:
    assert direct_route_signature([make_transition(1), make_transition(2)]) == "direct:1:2"
    assert direct_route_signature([make_transition(2), make_transition(1)]) != direct_route_signature([make_transition(1), make_transition(2)])


def test_restart_signature_is_deterministic_per_ancestor_chain() -> None:
    assert restart_route_signature(10, [1, 2, 3]) == "restart:10:1:2:3"
    assert restart_route_signature(10, [1, 2]) != restart_route_signature(10, [1, 2, 3])


# --- StrategySelector --------------------------------------------------------

def _candidate(strategy_type, cost, *, sample_count=5, last_observed_at=None, signature=None) -> RouteCandidate:
    return RouteCandidate(
        strategy_type=strategy_type, route=[], route_signature=signature or f"{strategy_type}-{cost}",
        hop_count=1, estimated_duration_ms=cost, sample_count=sample_count, last_observed_at=last_observed_at,
    )


def test_selector_picks_restart_when_historically_faster() -> None:
    selector = StrategySelector(minimum_samples=3)
    now = utc_now()
    candidates = [
        _candidate(RESTART, 1000, last_observed_at=now),
        _candidate(DIRECT_PATH, 3000, last_observed_at=now),
    ]

    chosen, reason = selector.select(candidates, now=now)

    assert chosen.strategy_type == RESTART
    assert reason == "restart_historically_faster"


def test_selector_picks_direct_when_historically_faster() -> None:
    selector = StrategySelector(minimum_samples=3)
    now = utc_now()
    candidates = [
        _candidate(RESTART, 3000, last_observed_at=now),
        _candidate(DIRECT_PATH, 1000, last_observed_at=now),
    ]

    chosen, reason = selector.select(candidates, now=now)

    assert chosen.strategy_type == DIRECT_PATH
    assert reason == "direct_route_historically_faster"


def test_selector_explores_cold_start_candidate_within_threshold() -> None:
    selector = StrategySelector(minimum_samples=3, exploration_threshold=1.25)
    now = utc_now()
    candidates = [
        _candidate(RESTART, 1000, sample_count=5, last_observed_at=now),
        _candidate(DIRECT_PATH, 1100, sample_count=0, signature="new-route"),  # within 1.25x of 1000
    ]

    chosen, reason = selector.select(candidates, now=now)

    assert chosen.route_signature == "new-route"
    assert reason == "cold_start_exploration"


def test_selector_does_not_explore_a_clearly_bad_unknown_route() -> None:
    selector = StrategySelector(minimum_samples=3, exploration_threshold=1.25)
    now = utc_now()
    candidates = [
        _candidate(RESTART, 1000, sample_count=5, last_observed_at=now),
        _candidate(DIRECT_PATH, 5000, sample_count=0, signature="bad-route"),  # way above 1.25x of 1000
    ]

    chosen, reason = selector.select(candidates, now=now)

    assert chosen.strategy_type == RESTART
    assert reason == "restart_historically_faster"


def test_selector_reexplores_a_stale_candidate() -> None:
    selector = StrategySelector(minimum_samples=3, reexploration_interval_seconds=3600)
    now = utc_now()
    stale_last_observed = now - timedelta(hours=2)
    candidates = [
        _candidate(RESTART, 1000, sample_count=5, last_observed_at=now),
        _candidate(DIRECT_PATH, 1050, sample_count=5, last_observed_at=stale_last_observed, signature="stale-route"),
    ]

    chosen, reason = selector.select(candidates, now=now)

    assert chosen.route_signature == "stale-route"
    assert reason == "stale_candidate_reexploration"


# --- MapperRoutePlannerService (DB-backed) ------------------------------------

def _seed_diamond_session(session):
    repository = SqlAlchemyMapperRepository(session)
    mapper_session = repository.create_session(package_name="com.planner.testapp", mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=3, max_actions=20, max_scrolls=0)
    root = repository.create_screen(session_id=mapper_session.id, fingerprint="root", screen_key="root", depth=0, ordinal=0)
    via_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="a", depth=1, ordinal=1)
    via_b = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="b", depth=1, ordinal=2)
    target = repository.create_screen(session_id=mapper_session.id, fingerprint="target", screen_key="target", depth=2, ordinal=3)

    def add_edge(from_screen, to_screen):
        node = repository.create_node(screen_id=from_screen.id, node_key=f"node-{from_screen.id}-{to_screen.id}", text="Go", clickable=True)
        action = repository.create_action(session_id=mapper_session.id, screen_id=from_screen.id, node_id=node.id, action_key=f"click:{from_screen.id}:{to_screen.id}", action_type="click", label="Go", safety=MapperActionSafety.SAFE)
        return repository.create_transition(session_id=mapper_session.id, from_screen_id=from_screen.id, action_id=action.id, to_screen_id=to_screen.id, result_type="clicked")

    add_edge(root, via_a)
    add_edge(via_a, target)
    add_edge(root, via_b)
    add_edge(via_b, target)

    return mapper_session, root, target


def test_planner_generates_direct_and_restart_candidates_and_picks_one() -> None:
    with SessionLocal() as session:
        mapper_session, root, target = _seed_diamond_session(session)
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session)
        plan = planner.plan(
            session_id=session_id, current_screen_id=root_id, target_screen_id=target_id,
            restart_option=RestartOption(root_screen_id=root_id, ancestor_step_ids=[100, 101]),
        )

    assert plan.from_screen_id == root_id
    assert plan.to_screen_id == target_id
    assert plan.strategy_type in (DIRECT_PATH, RESTART)
    assert plan.estimated_duration_ms > 0


def test_planner_learns_from_recorded_execution() -> None:
    with SessionLocal() as session:
        mapper_session, root, target = _seed_diamond_session(session)
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id

    restart_option = RestartOption(root_screen_id=root_id, ancestor_step_ids=[200, 201])

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session)
        plan = planner.plan(session_id=session_id, current_screen_id=root_id, target_screen_id=target_id, restart_option=restart_option)
        planner.record_execution(plan, actual_duration_ms=42.0, success=True)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        perf = repository.get_route_performance(plan.route_signature)
        assert perf is not None
        assert perf.sample_count == 1
        assert perf.last_duration_ms == 42.0


def test_planner_records_failure_in_reliability_counters() -> None:
    with SessionLocal() as session:
        mapper_session, root, target = _seed_diamond_session(session)
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id

    restart_option = RestartOption(root_screen_id=root_id, ancestor_step_ids=[300, 301])

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session)
        plan = planner.plan(session_id=session_id, current_screen_id=root_id, target_screen_id=target_id, restart_option=restart_option)
        planner.record_execution(plan, actual_duration_ms=9000.0, success=False)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        perf = repository.get_route_performance(plan.route_signature)
        assert perf is not None
        assert perf.success_count == 0
        assert perf.failure_count == 1


def test_planner_records_transition_observations_alongside_route_observation() -> None:
    with SessionLocal() as session:
        mapper_session, root, target = _seed_diamond_session(session)
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id
        transitions = SqlAlchemyMapperRepository(session).list_transitions(session_id)
        first_transition_id = transitions[0].id

    restart_option = RestartOption(root_screen_id=root_id, ancestor_step_ids=[400, 401])

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session)
        plan = planner.plan(session_id=session_id, current_screen_id=root_id, target_screen_id=target_id, restart_option=restart_option)
        planner.record_execution(
            plan, actual_duration_ms=42.0, success=True,
            transition_observations=[(first_transition_id, 15.0, True)],
        )
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        perf = repository.get_transition_performance(first_transition_id)
        assert perf is not None
        assert perf.sample_count == 1
        assert perf.last_duration_ms == 15.0
        assert perf.success_count == 1


def test_planner_does_not_reward_a_consistently_unreliable_fast_route() -> None:
    with SessionLocal() as session:
        mapper_session, root, target = _seed_diamond_session(session)
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id
        transitions = SqlAlchemyMapperRepository(session).list_transitions(session_id)
        fast_unreliable_signature = direct_route_signature(transitions[0:2])
        slow_reliable_signature = direct_route_signature(transitions[2:4])

    restart_option = RestartOption(root_screen_id=root_id, ancestor_step_ids=[600])

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        for is_success in [True] + [False] * 9:  # 1000ms but fails 90% of the time
            repository.record_route_observation(
                from_screen_id=root_id, to_screen_id=target_id, strategy_type=DIRECT_PATH,
                route_signature=fast_unreliable_signature, duration_ms=1000.0, success=is_success,
            )
        for _ in range(10):  # slower, but always succeeds
            repository.record_route_observation(
                from_screen_id=root_id, to_screen_id=target_id, strategy_type=DIRECT_PATH,
                route_signature=slow_reliable_signature, duration_ms=1500.0, success=True,
            )
        session.commit()

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session, strategy_selector=StrategySelector(minimum_samples=3))
        plan = planner.plan(session_id=session_id, current_screen_id=root_id, target_screen_id=target_id, restart_option=restart_option)

    assert plan.route_signature == slow_reliable_signature


def test_planner_future_decision_changes_after_a_new_faster_timing_is_recorded() -> None:
    with SessionLocal() as session:
        mapper_session, root, target = _seed_diamond_session(session)
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id
        transitions = SqlAlchemyMapperRepository(session).list_transitions(session_id)
        route_a_signature = direct_route_signature(transitions[0:2])
        route_b_signature = direct_route_signature(transitions[2:4])

    restart_option = RestartOption(root_screen_id=root_id, ancestor_step_ids=[700])
    selector = StrategySelector(minimum_samples=3)

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        for _ in range(5):
            repository.record_route_observation(
                from_screen_id=root_id, to_screen_id=target_id, strategy_type=DIRECT_PATH,
                route_signature=route_a_signature, duration_ms=2000.0, success=True,
            )
        for _ in range(5):
            repository.record_route_observation(
                from_screen_id=root_id, to_screen_id=target_id, strategy_type=DIRECT_PATH,
                route_signature=route_b_signature, duration_ms=1000.0, success=True,
            )
        session.commit()

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session, strategy_selector=selector)
        plan_before = planner.plan(session_id=session_id, current_screen_id=root_id, target_screen_id=target_id, restart_option=restart_option)

    assert plan_before.route_signature == route_b_signature  # cheaper so far

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        for _ in range(5):  # route A turns out to be much faster in practice now
            repository.record_route_observation(
                from_screen_id=root_id, to_screen_id=target_id, strategy_type=DIRECT_PATH,
                route_signature=route_a_signature, duration_ms=100.0, success=True,
            )
        session.commit()

    with SessionLocal() as session:
        planner = MapperRoutePlannerService(session, strategy_selector=selector)
        plan_after = planner.plan(session_id=session_id, current_screen_id=root_id, target_screen_id=target_id, restart_option=restart_option)

    assert plan_after.route_signature == route_a_signature  # the new timing flipped the decision
