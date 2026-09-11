from collections import defaultdict, deque


def topological_layers(nodes: list[dict]) -> list[list[dict]]:
    """Return executable layers while preserving declared dependencies."""
    by_id = {node["id"]: node for node in nodes}
    incoming = {node_id: set(node.get("depends_on", [])) for node_id, node in by_id.items()}
    dependents: dict[str, set[str]] = defaultdict(set)
    for node_id, dependencies in incoming.items():
        for dependency in dependencies:
            if dependency in by_id:
                dependents[dependency].add(node_id)
    layers: list[list[dict]] = []
    ready = deque(node_id for node_id, dependencies in incoming.items() if not dependencies)
    visited: set[str] = set()
    while ready:
        layer_ids = list(ready)
        ready.clear()
        layers.append([by_id[node_id] for node_id in layer_ids])
        for node_id in layer_ids:
            visited.add(node_id)
            for dependent in dependents[node_id]:
                incoming[dependent].discard(node_id)
                if not incoming[dependent]:
                    ready.append(dependent)
    if len(visited) != len(by_id):
        raise ValueError("Plan contains a dependency cycle or unknown dependency")
    return layers
