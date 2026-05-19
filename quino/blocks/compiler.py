"""Block diagram compiler: topological sort, cycle detection, wiring tables."""

from __future__ import annotations

from graphlib import TopologicalSorter

from quino.blocks.library import get_block_def
from quino.domain.blocks import BlockDiagram, CompiledDiagram


def _has_state(instance_id: str, diagram: BlockDiagram) -> bool:
    block_type = diagram.instances[instance_id].block_type
    try:
        return get_block_def(block_type).update is not None
    except ValueError:
        return False


def _find_cycle(dependencies: dict[str, set[str]]) -> list[str] | None:
    """Return a cycle if one exists, otherwise None."""
    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        stack.add(node)
        path.append(node)
        for neighbour in dependencies.get(node, set()):
            if neighbour not in visited:
                result = dfs(neighbour)
                if result is not None:
                    return result
            elif neighbour in stack:
                # Found cycle - extract it from path
                idx = path.index(neighbour)
                return path[idx:] + [neighbour]
        path.pop()
        stack.remove(node)
        return None

    for node in dependencies:
        if node not in visited:
            result = dfs(node)
            if result is not None:
                return result
    return None


def compile_diagram(diagram: BlockDiagram) -> CompiledDiagram:
    """Compile a BlockDiagram into a CompiledDiagram.

    Steps:
    1. Validate structural integrity.
    2. Build dependency graph (block A depends on B if B -> A).
    3. Break algebraic cycles at memoryful blocks (integrators, delays, PID).
    4. Reject cycles that contain no memoryful block.
    5. Compute topological execution order.
    6. Build wiring lookup table.
    """
    diagram.validate()

    # Build dependency graph and wiring
    dependencies: dict[str, set[str]] = {inst_id: set() for inst_id in diagram.instances}
    wiring: dict[tuple[str, str], list[tuple[str, str]]] = {}

    for conn in diagram.connections:
        dependencies[conn.dst_instance].add(conn.src_instance)
        src_key = (conn.src_instance, conn.src_port)
        wiring.setdefault(src_key, []).append((conn.dst_instance, conn.dst_port))

    # Check for required input ports that are not connected
    connected_inputs: set[tuple[str, str]] = set()
    for conn in diagram.connections:
        connected_inputs.add((conn.dst_instance, conn.dst_port))

    for instance_id, instance in diagram.instances.items():
        for port in instance.input_ports:
            if (instance_id, port.name) not in connected_inputs:
                raise ValueError(
                    f"Input port {port.name!r} on instance {instance_id!r} is not connected"
                )

    # Break cycles at memoryful blocks (Simulink-style)
    while True:
        cycle = _find_cycle(dependencies)
        if cycle is None:
            break
        cycle_nodes = set(cycle[:-1])  # last element repeats first
        breakers = [n for n in cycle_nodes if _has_state(n, diagram)]
        if not breakers:
            raise ValueError(
                f"Algebraic cycle detected among blocks: {' -> '.join(cycle)}. "
                "Insert a delay or integrator in the feedback loop."
            )
        # Break the cycle by removing the dependency edge *from* the breaker
        # *to* the next node in the cycle.  In the cycle list each node points
        # to the next one, so the edge we need to drop is breaker -> next_node
        # which lives inside dependencies[breaker].
        breaker = breakers[0]
        for i, node in enumerate(cycle[:-1]):
            if node == breaker:
                next_node = cycle[i + 1]
                dependencies[breaker].discard(next_node)
                break

    sorter = TopologicalSorter(dependencies)
    execution_order = list(sorter.static_order())

    return CompiledDiagram(
        source=diagram,
        execution_order=execution_order,
        wiring=wiring,
    )
