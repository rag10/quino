from __future__ import annotations

from quino.domain.workspace import Workspace


def mark_descendants_stale(workspace: Workspace, root_id: str) -> int:
    """Mark all analyses under root (case) and descendant cases as stale.

    Traverses the case hierarchy starting from root_id and finds all descendant
    cases. For each descendant case, marks all run entries belonging to its analyses
    as "stale" (if they were "ok").

    Args:
        workspace: The workspace containing cases, analyses, and runs.
        root_id: The ID of the case to start from (must be a case ID).

    Returns:
        The number of RunEntry instances flipped from "ok" to "stale".
    """
    affected_case_ids = _collect_descendant_case_ids(workspace, root_id)
    affected_analyses = [
        a for a in workspace.analyses
        if a.case_id is not None and a.case_id in affected_case_ids
    ]
    affected_analysis_ids = {a.id for a in affected_analyses}

    count = 0
    for run in workspace.runs:
        if run.analysis_id not in affected_analysis_ids:
            continue
        for entry in run.entries:
            if entry.status == "ok":
                entry.status = "stale"
                # Add stale reason if it's not already there
                if "ancestor edited" not in entry.stale_reasons:
                    entry.stale_reasons.append("ancestor edited")
                count += 1
    return count


def _collect_descendant_case_ids(workspace: Workspace, root_id: str) -> set[str]:
    """Collect all descendant case IDs (BFS from root).

    Args:
        workspace: The workspace containing cases.
        root_id: The ID of the root case.

    Returns:
        A set of case IDs including the root and all descendants.
    """
    result: set[str] = set()
    is_case = any(c.id == root_id for c in workspace.cases)

    if not is_case:
        # root_id is not a case; return empty set
        return result

    result.add(root_id)
    frontier = [root_id]

    while frontier:
        parent_id = frontier.pop()
        children = [c.id for c in workspace.cases if c.parent_case_id == parent_id]
        for cid in children:
            if cid not in result:
                result.add(cid)
                frontier.append(cid)

    return result
