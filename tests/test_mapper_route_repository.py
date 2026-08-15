from __future__ import annotations

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_route_repository import SqlAlchemyMapperRoutePerformanceRepository


def test_record_transition_observation_creates_and_updates() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session, ewma_alpha=0.5)
        repository.record_transition_observation(9001, duration_ms=1000, success=True)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session, ewma_alpha=0.5)
        perf = repository.get_transition_performance(9001)
        assert perf.sample_count == 1
        assert perf.mean_duration_ms == 1000
        assert perf.ewma_duration_ms == 1000
        assert perf.success_count == 1
        assert perf.failure_count == 0

        repository.record_transition_observation(9001, duration_ms=2000, success=False)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session, ewma_alpha=0.5)
        perf = repository.get_transition_performance(9001)
        assert perf.sample_count == 2
        assert perf.mean_duration_ms == 1500  # (1000 + 2000) / 2
        assert perf.ewma_duration_ms == 1500  # alpha=0.5: 0.5*2000 + 0.5*1000
        assert perf.success_count == 1
        assert perf.failure_count == 1
        assert perf.last_duration_ms == 2000


def test_bulk_get_transition_performance_returns_only_known_ones() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        repository.record_transition_observation(9101, duration_ms=500, success=True)
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        result = repository.bulk_get_transition_performance([9101, 9102])
        assert set(result.keys()) == {9101}


def test_record_route_observation_creates_and_updates_by_signature() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session, ewma_alpha=0.5)
        repository.record_route_observation(
            from_screen_id=1, to_screen_id=2, strategy_type="direct_path",
            route_signature="sig-a", duration_ms=1800, success=True,
        )
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session, ewma_alpha=0.5)
        perf = repository.get_route_performance("sig-a")
        assert perf is not None
        assert perf.strategy_type == "direct_path"
        assert perf.sample_count == 1

        repository.record_route_observation(
            from_screen_id=1, to_screen_id=2, strategy_type="direct_path",
            route_signature="sig-a", duration_ms=2200, success=True,
        )
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        perf = repository.get_route_performance("sig-a")
        assert perf.sample_count == 2
        assert perf.mean_duration_ms == 2000
