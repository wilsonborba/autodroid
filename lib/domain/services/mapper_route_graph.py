from __future__ import annotations

import heapq
from typing import Callable

from lib.domain.models.mapper_model import MapperTransition

WeightFn = Callable[[MapperTransition], float]

Adjacency = dict[int, list[MapperTransition]]


def build_adjacency(transitions: list[MapperTransition]) -> Adjacency:
    """Only successful clicks are real, traversable edges (issue #24): a skipped/failed
    transition doesn't lead anywhere real, it can't be part of a route."""
    adjacency: Adjacency = {}
    for transition in transitions:
        if transition.result_type != "clicked" or transition.to_screen_id is None:
            continue
        adjacency.setdefault(transition.from_screen_id, []).append(transition)
    return adjacency


def dijkstra_shortest_path(
    adjacency: Adjacency,
    source: int,
    target: int,
    weight_fn: WeightFn,
    *,
    excluded_edge_ids: set[int] | None = None,
    excluded_nodes: set[int] | None = None,
) -> list[MapperTransition] | None:
    """Shortest path by `weight_fn` (not hop count), as a list of transitions in order.
    Returns `[]` when source == target (already there), `None` when unreachable."""
    if source == target:
        return []
    excluded_edge_ids = excluded_edge_ids or set()
    excluded_nodes = excluded_nodes or set()
    if source in excluded_nodes or target in excluded_nodes:
        return None

    distances: dict[int, float] = {source: 0.0}
    previous: dict[int, tuple[int, MapperTransition]] = {}
    visited: set[int] = set()
    heap: list[tuple[float, int]] = [(0.0, source)]

    while heap:
        dist, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        if node == target:
            break
        for transition in adjacency.get(node, []):
            if transition.id in excluded_edge_ids:
                continue
            neighbor = transition.to_screen_id
            if neighbor is None or neighbor in excluded_nodes:
                continue
            new_dist = dist + weight_fn(transition)
            if neighbor not in distances or new_dist < distances[neighbor] - 1e-9:
                distances[neighbor] = new_dist
                previous[neighbor] = (node, transition)
                heapq.heappush(heap, (new_dist, neighbor))

    if target not in distances:
        return None

    path: list[MapperTransition] = []
    current = target
    while current != source:
        prev_node, transition = previous[current]
        path.append(transition)
        current = prev_node
    path.reverse()
    return path


def _node_sequence(source: int, path: list[MapperTransition]) -> list[int]:
    sequence = [source]
    for transition in path:
        sequence.append(transition.to_screen_id)
    return sequence


def yen_k_shortest_paths(
    adjacency: Adjacency,
    source: int,
    target: int,
    k: int,
    weight_fn: WeightFn,
) -> list[list[MapperTransition]]:
    """K shortest *simple* (loopless) paths between source and target, Yen's algorithm on top
    of `dijkstra_shortest_path`. Not a definitive planner by itself (issue #24): this only
    generates candidates, `CostEstimator`/`StrategySelector` pick between them and the restart
    candidate. Returns fewer than `k` paths if the graph doesn't have that many simple routes."""
    if k <= 0:
        return []

    first_path = dijkstra_shortest_path(adjacency, source, target, weight_fn)
    if first_path is None:
        return []

    accepted: list[list[MapperTransition]] = [first_path]
    candidates: list[tuple[float, list[MapperTransition]]] = []
    seen_signatures: set[tuple[int, ...]] = {tuple(t.id for t in first_path)}

    while len(accepted) < k:
        previous_path = accepted[-1]
        node_sequence = _node_sequence(source, previous_path)

        for i in range(len(previous_path)):
            spur_node = node_sequence[i]
            root_path = previous_path[:i]
            root_signature = tuple(t.id for t in root_path)

            # don't reuse an edge that any already-accepted path also takes right after this
            # same root, that's exactly what would make the spur search re-find the same path
            excluded_edge_ids: set[int] = set()
            for path in accepted:
                if len(path) > i and tuple(t.id for t in path[:i]) == root_signature:
                    excluded_edge_ids.add(path[i].id)

            # root nodes before the spur (not the spur itself) are off-limits, or the spur
            # search could loop back through the root and produce a non-simple path
            excluded_nodes = set(node_sequence[:i])

            spur_path = dijkstra_shortest_path(
                adjacency, spur_node, target, weight_fn,
                excluded_edge_ids=excluded_edge_ids, excluded_nodes=excluded_nodes,
            )
            if spur_path is None:
                continue

            total_path = root_path + spur_path
            signature = tuple(t.id for t in total_path)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            candidates.append((sum(weight_fn(t) for t in total_path), total_path))

        if not candidates:
            break

        candidates.sort(key=lambda item: item[0])
        accepted.append(candidates.pop(0)[1])

    return accepted[:k]
