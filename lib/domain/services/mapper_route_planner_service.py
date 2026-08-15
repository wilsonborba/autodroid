from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from lib.core.logs import get_logger
from lib.core.utils.clock import utc_now
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.local.mapper_route_repository import SqlAlchemyMapperRoutePerformanceRepository
from lib.domain.models.mapper_model import MapperTransition
from lib.domain.services.mapper_route_graph import build_adjacency, yen_k_shortest_paths

DIRECT_PATH = "direct_path"
RESTART = "restart"

DEFAULT_K = 3
DEFAULT_TRANSITION_COST_MS = 1500.0
DEFAULT_RESTART_COST_MS = 2500.0
DEFAULT_UNKNOWN_EDGE_PENALTY_MS = 800.0
DEFAULT_EXPLORATION_THRESHOLD = 1.25
DEFAULT_MINIMUM_SAMPLES = 3
DEFAULT_REEXPLORATION_INTERVAL_SECONDS = 3600
DEFAULT_RELIABILITY_PENALTY_WEIGHT = 1.0


@dataclass
class RouteCandidate:
    strategy_type: str  # DIRECT_PATH | RESTART
    route: list[MapperTransition]  # the transitions to walk; empty for restart
    route_signature: str
    hop_count: int
    estimated_duration_ms: float
    sample_count: int = 0
    last_observed_at: datetime | None = None


@dataclass
class ExecutionPlan:
    strategy_type: str
    route: list[MapperTransition]
    route_signature: str
    from_screen_id: int
    to_screen_id: int
    estimated_duration_ms: float
    reason: str


class CostEstimator:
    """Turns a transition (edge) or a candidate route into an estimated cost in ms.

    Priority for a single edge: EWMA (recent real observations) -> default transition cost.
    A route's cost is the sum of its edges' costs plus a penalty per edge with no history yet,
    so a route full of unknowns doesn't look artificially cheap just because nothing failed it
    yet (issue #24, "penalidade de incerteza")."""

    def __init__(
        self,
        *,
        default_transition_cost_ms: float = DEFAULT_TRANSITION_COST_MS,
        unknown_edge_penalty_ms: float = DEFAULT_UNKNOWN_EDGE_PENALTY_MS,
        reliability_penalty_weight: float = DEFAULT_RELIABILITY_PENALTY_WEIGHT,
    ) -> None:
        self.default_transition_cost_ms = default_transition_cost_ms
        self.unknown_edge_penalty_ms = unknown_edge_penalty_ms
        self.reliability_penalty_weight = reliability_penalty_weight

    def edge_cost(self, transition: MapperTransition, performance_by_transition_id: dict) -> tuple[float, bool]:
        perf = performance_by_transition_id.get(transition.id)
        if perf is not None and perf.sample_count > 0:
            return perf.ewma_duration_ms, True
        return self.default_transition_cost_ms, False

    def weight_fn(self, performance_by_transition_id: dict):
        def _weight(transition: MapperTransition) -> float:
            cost, _ = self.edge_cost(transition, performance_by_transition_id)
            return cost
        return _weight

    def estimate_route(self, route: list[MapperTransition], performance_by_transition_id: dict) -> float:
        total = 0.0
        unknown_edges = 0
        for transition in route:
            cost, known = self.edge_cost(transition, performance_by_transition_id)
            total += cost
            if not known:
                unknown_edges += 1
        return total + unknown_edges * self.unknown_edge_penalty_ms

    def apply_reliability_penalty(self, estimated_duration_ms: float, *, success_count: int, failure_count: int) -> float:
        """A route that fails often shouldn't look cheap just because it's fast when it works
        (issue #24, "o planner não deve premiar rotas consistentemente instáveis"). Deliberately
        a plain linear penalty on the observed failure rate, not a sophisticated reliability
        scoring system: at a 100% failure rate the estimate doubles by default."""
        total_samples = success_count + failure_count
        if total_samples == 0:
            return estimated_duration_ms
        failure_rate = failure_count / total_samples
        return estimated_duration_ms * (1 + self.reliability_penalty_weight * failure_rate)


class StrategySelector:
    """Exploit the historically cheapest candidate, or controlled exploration otherwise: a
    candidate that never ran, hasn't reached a minimum sample size, or hasn't been retried in a
    while, gets picked instead, but only if its estimate isn't clearly worse than the best known
    one (issue #24, "exploração controlada"). No bandit/ML, a deterministic testable policy."""

    def __init__(
        self,
        *,
        exploration_threshold: float = DEFAULT_EXPLORATION_THRESHOLD,
        minimum_samples: int = DEFAULT_MINIMUM_SAMPLES,
        reexploration_interval_seconds: float = DEFAULT_REEXPLORATION_INTERVAL_SECONDS,
    ) -> None:
        self.exploration_threshold = exploration_threshold
        self.minimum_samples = minimum_samples
        self.reexploration_interval_seconds = reexploration_interval_seconds

    def select(self, candidates: list[RouteCandidate], *, now: datetime | None = None) -> tuple[RouteCandidate, str]:
        if not candidates:
            raise ValueError("select() needs at least one candidate")
        now = now or utc_now()
        reference_cost = min(c.estimated_duration_ms for c in candidates)

        def is_explorable(candidate: RouteCandidate) -> bool:
            if candidate.estimated_duration_ms > reference_cost * self.exploration_threshold:
                return False
            if candidate.sample_count < self.minimum_samples:
                return True
            if candidate.last_observed_at is not None and (now - _as_aware_utc(candidate.last_observed_at)).total_seconds() >= self.reexploration_interval_seconds:
                return True
            return False

        explorable = [c for c in candidates if is_explorable(c)]
        if explorable:
            chosen = min(explorable, key=lambda c: c.sample_count)
            reason = "cold_start_exploration" if chosen.sample_count < self.minimum_samples else "stale_candidate_reexploration"
            return chosen, reason

        best = min(candidates, key=lambda c: c.estimated_duration_ms)
        others_have_restart = any(c.strategy_type == RESTART for c in candidates if c is not best)
        others_have_direct = any(c.strategy_type == DIRECT_PATH for c in candidates if c is not best)
        if best.strategy_type == RESTART and others_have_direct:
            return best, "restart_historically_faster"
        if best.strategy_type == DIRECT_PATH and others_have_restart:
            return best, "direct_route_historically_faster"
        return best, "lowest_expected_cost"


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip even for a `DateTime(timezone=True)` column, so a
    freshly loaded `last_observed_at` can come back naive. It was always written with
    `utc_now()`, so a naive value is assumed to already be UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def direct_route_signature(route: list[MapperTransition]) -> str:
    return "direct:" + ":".join(str(transition.id) for transition in route)


def restart_route_signature(root_screen_id: int, ancestor_step_ids: list[int]) -> str:
    return f"restart:{root_screen_id}:" + ":".join(str(step_id) for step_id in ancestor_step_ids)


@dataclass
class RestartOption:
    """What a restart candidate would replay: force-stop + relaunch, then the known ancestor
    chain from the root (issue #23's existing mechanism), identified by its step ids so the
    signature is stable regardless of how those steps get resolved at execution time."""

    root_screen_id: int
    ancestor_step_ids: list[int] = field(default_factory=list)


class MapperRoutePlannerService:
    """Facade: generates candidates (K direct paths via Yen's + the restart option), estimates
    and scores them, picks one, and records real observations after execution. The Flow stays
    declarative; this only produces a runtime `ExecutionPlan`, never rewrites a saved Flow."""

    def __init__(
        self,
        session: Session,
        *,
        k: int = DEFAULT_K,
        cost_estimator: CostEstimator | None = None,
        strategy_selector: StrategySelector | None = None,
        default_restart_cost_ms: float = DEFAULT_RESTART_COST_MS,
    ) -> None:
        self.logger = get_logger(__name__)
        self.mapper_repository = SqlAlchemyMapperRepository(session)
        self.performance_repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        self.k = k
        self.cost_estimator = cost_estimator or CostEstimator()
        self.strategy_selector = strategy_selector or StrategySelector()
        self.default_restart_cost_ms = default_restart_cost_ms

    def plan(self, *, session_id: int, current_screen_id: int, target_screen_id: int, restart_option: RestartOption) -> ExecutionPlan:
        transitions = self.mapper_repository.list_transitions(session_id)
        adjacency = build_adjacency(transitions)
        performance_by_transition_id = self.performance_repository.bulk_get_transition_performance([t.id for t in transitions])

        direct_paths = yen_k_shortest_paths(
            adjacency, current_screen_id, target_screen_id, self.k,
            self.cost_estimator.weight_fn(performance_by_transition_id),
        )

        candidates: list[RouteCandidate] = []
        for path in direct_paths:
            signature = direct_route_signature(path)
            route_perf = self.performance_repository.get_route_performance(signature)
            if route_perf is not None and route_perf.sample_count > 0:
                estimated = self.cost_estimator.apply_reliability_penalty(
                    route_perf.ewma_duration_ms,
                    success_count=route_perf.success_count, failure_count=route_perf.failure_count,
                )
            else:
                estimated = self.cost_estimator.estimate_route(path, performance_by_transition_id)
            candidates.append(RouteCandidate(
                strategy_type=DIRECT_PATH,
                route=path,
                route_signature=signature,
                hop_count=len(path),
                estimated_duration_ms=estimated,
                sample_count=route_perf.sample_count if route_perf else 0,
                last_observed_at=route_perf.last_observed_at if route_perf else None,
            ))

        restart_signature = restart_route_signature(restart_option.root_screen_id, restart_option.ancestor_step_ids)
        restart_perf = self.performance_repository.get_route_performance(restart_signature)
        restart_default_cost = self.default_restart_cost_ms + len(restart_option.ancestor_step_ids) * self.cost_estimator.default_transition_cost_ms
        if restart_perf is not None and restart_perf.sample_count > 0:
            restart_estimated = self.cost_estimator.apply_reliability_penalty(
                restart_perf.ewma_duration_ms,
                success_count=restart_perf.success_count, failure_count=restart_perf.failure_count,
            )
        else:
            restart_estimated = restart_default_cost
        candidates.append(RouteCandidate(
            strategy_type=RESTART,
            route=[],
            route_signature=restart_signature,
            hop_count=len(restart_option.ancestor_step_ids),
            estimated_duration_ms=restart_estimated,
            sample_count=restart_perf.sample_count if restart_perf else 0,
            last_observed_at=restart_perf.last_observed_at if restart_perf else None,
        ))

        chosen, reason = self.strategy_selector.select(candidates)
        self.logger.info(
            "Route plan %s -> %s: strategy=%s reason=%s estimated_ms=%.0f (%s candidate(s) considered)",
            current_screen_id, target_screen_id, chosen.strategy_type, reason, chosen.estimated_duration_ms, len(candidates),
        )
        return ExecutionPlan(
            strategy_type=chosen.strategy_type,
            route=chosen.route,
            route_signature=chosen.route_signature,
            from_screen_id=current_screen_id,
            to_screen_id=target_screen_id,
            estimated_duration_ms=chosen.estimated_duration_ms,
            reason=reason,
        )

    def record_execution(
        self,
        plan: ExecutionPlan,
        *,
        actual_duration_ms: float,
        success: bool,
        transition_observations: list[tuple[int, float, bool]] | None = None,
    ) -> None:
        """Only real, measured observations land here, never estimates (issue #24)."""
        self.performance_repository.record_route_observation(
            from_screen_id=plan.from_screen_id,
            to_screen_id=plan.to_screen_id,
            strategy_type=plan.strategy_type,
            route_signature=plan.route_signature,
            duration_ms=actual_duration_ms,
            success=success,
        )
        for transition_id, duration_ms, edge_success in transition_observations or []:
            self.performance_repository.record_transition_observation(transition_id, duration_ms=duration_ms, success=edge_success)
        self.logger.info(
            "Recorded route execution %s (%s): %.0fms success=%s",
            plan.route_signature, plan.strategy_type, actual_duration_ms, success,
        )
