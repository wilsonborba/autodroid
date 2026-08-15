from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.core.utils.clock import utc_now
from lib.domain.models.mapper_route_model import MapperRoutePerformance, MapperTransitionPerformance

DEFAULT_EWMA_ALPHA = 0.3


class SqlAlchemyMapperRoutePerformanceRepository:
    """Persists learned planner state (issue #24): observed timings per transition and per whole
    route. Not a general execution history, only real measured observations ever land here."""

    def __init__(self, session: Session, *, ewma_alpha: float = DEFAULT_EWMA_ALPHA) -> None:
        self.session = session
        self.ewma_alpha = ewma_alpha

    # --- per-transition ---------------------------------------------------

    def get_transition_performance(self, transition_id: int) -> MapperTransitionPerformance | None:
        stmt = select(MapperTransitionPerformance).where(MapperTransitionPerformance.transition_id == transition_id)
        return self.session.scalar(stmt)

    def bulk_get_transition_performance(self, transition_ids: list[int]) -> dict[int, MapperTransitionPerformance]:
        if not transition_ids:
            return {}
        stmt = select(MapperTransitionPerformance).where(MapperTransitionPerformance.transition_id.in_(transition_ids))
        return {perf.transition_id: perf for perf in self.session.scalars(stmt)}

    def record_transition_observation(self, transition_id: int, *, duration_ms: float, success: bool) -> MapperTransitionPerformance:
        perf = self.get_transition_performance(transition_id)
        if perf is None:
            perf = MapperTransitionPerformance(transition_id=transition_id, sample_count=0, mean_duration_ms=0.0, ewma_duration_ms=0.0, success_count=0, failure_count=0)
            self.session.add(perf)
        self._apply_observation(perf, duration_ms=duration_ms, success=success)
        self.session.flush()
        return perf

    # --- whole route --------------------------------------------------------

    def get_route_performance(self, route_signature: str) -> MapperRoutePerformance | None:
        stmt = select(MapperRoutePerformance).where(MapperRoutePerformance.route_signature == route_signature)
        return self.session.scalar(stmt)

    def record_route_observation(
        self,
        *,
        from_screen_id: int,
        to_screen_id: int,
        strategy_type: str,
        route_signature: str,
        duration_ms: float,
        success: bool,
    ) -> MapperRoutePerformance:
        perf = self.get_route_performance(route_signature)
        if perf is None:
            perf = MapperRoutePerformance(
                from_screen_id=from_screen_id,
                to_screen_id=to_screen_id,
                strategy_type=strategy_type,
                route_signature=route_signature,
                sample_count=0,
                mean_duration_ms=0.0,
                ewma_duration_ms=0.0,
                success_count=0,
                failure_count=0,
            )
            self.session.add(perf)
        self._apply_observation(perf, duration_ms=duration_ms, success=success)
        self.session.flush()
        return perf

    # --- shared update logic (same fields on both models) --------------------

    def _apply_observation(self, perf: MapperTransitionPerformance | MapperRoutePerformance, *, duration_ms: float, success: bool) -> None:
        perf.sample_count += 1
        # running mean, avoids needing every raw sample to recompute it
        perf.mean_duration_ms += (duration_ms - perf.mean_duration_ms) / perf.sample_count
        perf.ewma_duration_ms = duration_ms if perf.sample_count == 1 else (self.ewma_alpha * duration_ms + (1 - self.ewma_alpha) * perf.ewma_duration_ms)
        if success:
            perf.success_count += 1
        else:
            perf.failure_count += 1
        perf.last_duration_ms = duration_ms
        perf.last_observed_at = utc_now()
