from __future__ import annotations

from quino.domain.workspace import Workspace


def mark_descendants_stale(workspace: Workspace, root_case_id: str) -> int:
    """Mark all runs in root_case_id and its descendants as stale."""
    descendant_ids = _collect_descendant_case_ids(workspace, root_case_id)
    count = 0
    for cid in descendant_ids:
        case = workspace.cases.get(cid)
        if case is None:
            continue
        # The standalone Run entity was removed; run state now lives on Analysis.
        for run in case.analyses:
            if run.status in {"ok", "partial"}:
                run.status = "stale"
                if "ancestor edited" not in run.warnings:
                    run.warnings.append("ancestor edited")
                count += 1
    return count


def _collect_descendant_case_ids(workspace: Workspace, root_id: str) -> set[str]:
    """Return root_id and all descendants (BFS)."""
    if root_id not in workspace.cases:
        return set()
    result: set[str] = {root_id}
    frontier = [root_id]
    while frontier:
        parent_id = frontier.pop()
        for cid, c in workspace.cases.items():
            if c.parent_case_id == parent_id and cid not in result:
                result.add(cid)
                frontier.append(cid)
    return result
