from __future__ import annotations

from lib.domain.models.mapper_model import MapperTransition
from lib.domain.services.mapper_route_graph import build_adjacency, dijkstra_shortest_path, yen_k_shortest_paths


def make_transition(id: int, from_screen_id: int, to_screen_id: int | None, *, result_type: str = "clicked", action_id: int | None = None) -> MapperTransition:
    transition = MapperTransition(session_id=1, from_screen_id=from_screen_id, action_id=action_id or id, to_screen_id=to_screen_id, result_type=result_type)
    transition.id = id
    return transition


def weight_by_id(weights: dict[int, float]):
    def weight_fn(transition: MapperTransition) -> float:
        return weights.get(transition.id, 1.0)
    return weight_fn


def test_build_adjacency_ignores_failed_and_skipped_transitions() -> None:
    transitions = [
        make_transition(1, 1, 2),
        make_transition(2, 1, None, result_type="failed_click"),
        make_transition(3, 1, 3, result_type="skipped_dangerous"),
    ]

    adjacency = build_adjacency(transitions)

    assert len(adjacency[1]) == 1
    assert adjacency[1][0].id == 1


def test_dijkstra_returns_none_when_unreachable() -> None:
    adjacency = build_adjacency([make_transition(1, 1, 2)])

    assert dijkstra_shortest_path(adjacency, 1, 99, weight_by_id({})) is None


def test_dijkstra_returns_empty_path_when_already_at_target() -> None:
    adjacency = build_adjacency([make_transition(1, 1, 2)])

    assert dijkstra_shortest_path(adjacency, 1, 1, weight_by_id({})) == []


def test_dijkstra_prefers_lower_weight_over_fewer_hops() -> None:
    # 1 -> 2 -> 4 costs 10 (2 hops); 1 -> 3 -> 5 -> 4 costs 6 (3 hops): weighted should win, not hop count
    transitions = [
        make_transition(1, 1, 2), make_transition(2, 2, 4),
        make_transition(3, 1, 3), make_transition(4, 3, 5), make_transition(5, 5, 4),
    ]
    weights = {1: 5, 2: 5, 3: 2, 4: 2, 5: 2}
    adjacency = build_adjacency(transitions)

    path = dijkstra_shortest_path(adjacency, 1, 4, weight_by_id(weights))

    assert [t.id for t in path] == [3, 4, 5]


def test_yen_returns_both_paths_of_a_diamond_graph() -> None:
    transitions = [
        make_transition(1, 1, 2), make_transition(2, 2, 4),
        make_transition(3, 1, 3), make_transition(4, 3, 4),
    ]
    adjacency = build_adjacency(transitions)

    paths = yen_k_shortest_paths(adjacency, 1, 4, k=2, weight_fn=weight_by_id({}))

    assert len(paths) == 2
    signatures = {tuple(t.id for t in path) for path in paths}
    assert signatures == {(1, 2), (3, 4)}


def test_yen_returns_fewer_paths_than_k_when_graph_has_no_more() -> None:
    transitions = [make_transition(1, 1, 2), make_transition(2, 2, 4)]
    adjacency = build_adjacency(transitions)

    paths = yen_k_shortest_paths(adjacency, 1, 4, k=5, weight_fn=weight_by_id({}))

    assert len(paths) == 1
    assert [t.id for t in paths[0]] == [1, 2]


def test_yen_returns_no_paths_when_target_unreachable() -> None:
    adjacency = build_adjacency([make_transition(1, 1, 2)])

    assert yen_k_shortest_paths(adjacency, 1, 99, k=3, weight_fn=weight_by_id({})) == []


def test_yen_paths_are_always_simple_even_with_a_cycle_in_the_graph() -> None:
    # 1 -> 2 -> 3 -> 1 (cycle) and 2 -> 4 (exit to target)
    transitions = [
        make_transition(1, 1, 2),
        make_transition(2, 2, 3),
        make_transition(3, 3, 1),
        make_transition(4, 2, 4),
    ]
    adjacency = build_adjacency(transitions)

    paths = yen_k_shortest_paths(adjacency, 1, 4, k=3, weight_fn=weight_by_id({}))

    assert len(paths) == 1
    node_ids = [1] + [t.to_screen_id for t in paths[0]]
    assert len(node_ids) == len(set(node_ids))  # no repeated screen in the path


def test_yen_ranks_candidates_by_total_weight() -> None:
    # three parallel routes 1->4 with different total costs, expect ascending order
    transitions = [
        make_transition(1, 1, 2), make_transition(2, 2, 4),  # cost 10
        make_transition(3, 1, 3), make_transition(4, 3, 4),  # cost 4
        make_transition(5, 1, 5), make_transition(6, 5, 4),  # cost 7
    ]
    weights = {1: 5, 2: 5, 3: 2, 4: 2, 5: 3, 6: 4}
    adjacency = build_adjacency(transitions)

    paths = yen_k_shortest_paths(adjacency, 1, 4, k=3, weight_fn=weight_by_id(weights))

    costs = [sum(weight_by_id(weights)(t) for t in path) for path in paths]
    assert costs == sorted(costs)
    assert [t.id for t in paths[0]] == [3, 4]
