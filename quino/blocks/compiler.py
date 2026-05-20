"""Block diagram compiler: topological sort, cycle detection, wiring tables."""

from __future__ import annotations

from graphlib import TopologicalSorter

from quino.blocks.library import get_block_def
from quino.domain.blocks import BlockDiagram, CompiledDiagram, Connection


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


def _expand_subsystems(diagram: BlockDiagram) -> BlockDiagram:
    """Return a new diagram with all subsystem instances flattened."""
    from copy import deepcopy

    new_instances = dict(diagram.instances)
    new_connections = list(diagram.connections)
    changed = True

    while changed:
        changed = False
        to_remove_instances: set[str] = set()
        to_remove_connections: list[int] = []
        added_connections: list[Connection] = []

        for idx, conn in enumerate(new_connections):
            src_inst = new_instances.get(conn.src_instance)
            dst_inst = new_instances.get(conn.dst_instance)

            # Handle connection from external source into a subsystem
            if dst_inst is not None and dst_inst.internal_diagram is not None:
                sub = dst_inst.internal_diagram
                prefix = dst_inst.instance_id + "/"
                # Find Inport blocks inside subsystem that match the port name
                inport_id = None
                for internal_id, internal_inst in sub.instances.items():
                    if internal_inst.block_type == "Inport" and internal_inst.parameter("port_name", "in") == conn.dst_port:
                        inport_id = prefix + internal_id
                        break
                if inport_id is not None:
                    # Replace connection target with the internal inport
                    new_connections[idx] = Connection(
                        conn.src_instance, conn.src_port,
                        inport_id, "in",
                    )
                    changed = True

            # Handle connection from subsystem to external destination
            if src_inst is not None and src_inst.internal_diagram is not None:
                sub = src_inst.internal_diagram
                prefix = src_inst.instance_id + "/"
                # Find Outport blocks inside subsystem that match the port name
                outport_id = None
                for internal_id, internal_inst in sub.instances.items():
                    if internal_inst.block_type == "Outport" and internal_inst.parameter("port_name", "out") == conn.src_port:
                        outport_id = prefix + internal_id
                        break
                if outport_id is not None:
                    # Replace connection source with the internal outport
                    new_connections[idx] = Connection(
                        outport_id, "out",
                        conn.dst_instance, conn.dst_port,
                    )
                    changed = True

        # After rewiring external connections, expand any subsystem whose
        # ports are no longer referenced directly in connections
        for inst_id, inst in list(new_instances.items()):
            if inst.internal_diagram is None:
                continue
            if inst_id in to_remove_instances:
                continue

            # Check if there are still direct connections to this subsystem
            still_connected = any(
                c.src_instance == inst_id or c.dst_instance == inst_id
                for c in new_connections
            )
            if still_connected:
                # Not all ports are mapped yet; skip for now
                continue

            sub = inst.internal_diagram
            prefix = inst_id + "/"
            # Add internal instances with prefixed IDs
            for internal_id, internal_inst in sub.instances.items():
                new_id = prefix + internal_id
                new_inst = deepcopy(internal_inst)
                new_inst.instance_id = new_id
                new_instances[new_id] = new_inst

            # Add internal connections with prefixed IDs
            for internal_conn in sub.connections:
                added_connections.append(Connection(
                    prefix + internal_conn.src_instance,
                    internal_conn.src_port,
                    prefix + internal_conn.dst_instance,
                    internal_conn.dst_port,
                ))

            to_remove_instances.add(inst_id)
            changed = True

        # Remove expanded subsystems
        for inst_id in to_remove_instances:
            del new_instances[inst_id]

        # Remove connections that were replaced (src_instance or dst_instance no longer exists)
        new_connections = [
            c for c in new_connections
            if c.src_instance in new_instances and c.dst_instance in new_instances
        ]
        new_connections.extend(added_connections)

    return BlockDiagram(instances=new_instances, connections=new_connections)


def compile_diagram(diagram: BlockDiagram) -> CompiledDiagram:
    """Compile a BlockDiagram into a CompiledDiagram.

    Steps:
    1. Expand subsystems.
    2. Validate structural integrity.
    3. Build dependency graph (block A depends on B if B -> A).
    4. Break algebraic cycles at memoryful blocks (integrators, delays, PID).
    5. Reject cycles that contain no memoryful block.
    6. Compute topological execution order.
    7. Build wiring lookup table.
    """
    diagram = _expand_subsystems(diagram)
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
