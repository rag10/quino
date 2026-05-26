"""Compute a per-case summary distinguishing local diffs from inherited ones.

The summary classifies every override / structural delta as either ``local``
(set directly on the case being inspected) or ``inherited`` (set on an
ancestor case). When the same path is set on both an ancestor and the case
itself, the case entry wins and is tagged ``local_shadowing_inherited``.

The result is intentionally simple and JSON-friendly so it can be rendered
in the model tree, inspector, and workflow tree without each consumer
re-walking the case chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quino.domain.workspace import Case
from quino.services.workspace_composition import _resolve_case_chain


@dataclass
class InvariantOverride:
    path: str
    value: Any
    unit: str
    source_case_id: str  # case that last set this path
    is_local: bool       # True if source_case_id == target case
    shadows_inherited: bool = False  # local and at least one ancestor set it too


@dataclass
class StructuralAddition:
    domain: str          # e.g. "bodies", "joints", "blocks"
    entity_id: str
    source_case_id: str
    is_local: bool


@dataclass
class StructuralRemoval:
    kind: str            # "entity" or "connection"
    payload: Any         # entity_id (str) for entity, 4-tuple for connection
    source_case_id: str
    is_local: bool


@dataclass
class ReferenceOverride:
    entity_id: str
    prop: str
    value: Any
    source_case_id: str
    is_local: bool
    shadows_inherited: bool = False


@dataclass
class CaseDiffSummary:
    case_id: str
    invariant_overrides: list[InvariantOverride] = field(default_factory=list)
    additions: list[StructuralAddition] = field(default_factory=list)
    removals: list[StructuralRemoval] = field(default_factory=list)
    reference_overrides: list[ReferenceOverride] = field(default_factory=list)

    def local_count(self) -> int:
        return (
            sum(1 for i in self.invariant_overrides if i.is_local)
            + sum(1 for a in self.additions if a.is_local)
            + sum(1 for r in self.removals if r.is_local)
            + sum(1 for r in self.reference_overrides if r.is_local)
        )

    def inherited_count(self) -> int:
        return (
            sum(1 for i in self.invariant_overrides if not i.is_local)
            + sum(1 for a in self.additions if not a.is_local)
            + sum(1 for r in self.removals if not r.is_local)
            + sum(1 for r in self.reference_overrides if not r.is_local)
        )


def build_case_diff_summary(project, case: Case) -> CaseDiffSummary:
    """Return a structured diff that separates local from inherited entries.

    The case chain is walked from the root ancestor down to ``case``. For each
    path, the *closest* setter (deepest case in the chain) is the visible one;
    if that setter is the target case, the entry is local, otherwise inherited.
    """
    chain = _resolve_case_chain(project, case)
    target_id = case.id

    summary = CaseDiffSummary(case_id=target_id)

    # --- invariant_values -----------------------------------------------------
    # First gather, by path, the deepest setter and whether any ancestor also
    # set it. Walk root->leaf so the leaf overrides ancestors naturally.
    invariant_state: dict[str, tuple[str, Any, str, bool]] = {}
    #  path -> (source_case_id, value, unit, ancestor_also_set)
    for inherited_case in chain:
        for path, scalar in inherited_case.invariant_values.items():
            prior = invariant_state.get(path)
            ancestor_set = prior is not None
            invariant_state[path] = (
                inherited_case.id,
                scalar.value,
                getattr(scalar, "unit", ""),
                ancestor_set or (prior is not None),
            )
    for path, (src_id, val, unit, ancestor_set) in invariant_state.items():
        is_local = src_id == target_id
        summary.invariant_overrides.append(
            InvariantOverride(
                path=path,
                value=val,
                unit=unit,
                source_case_id=src_id,
                is_local=is_local,
                shadows_inherited=is_local and ancestor_set,
            )
        )

    # --- added_entities -------------------------------------------------------
    seen_entity_ids: set[str] = set()
    for inherited_case in chain:
        for domain, entities in inherited_case.added_entities.items():
            for ent in entities:
                eid = ent.get("id") or ent.get("instance_id")
                if not eid or eid in seen_entity_ids:
                    continue
                seen_entity_ids.add(eid)
                summary.additions.append(
                    StructuralAddition(
                        domain=domain,
                        entity_id=eid,
                        source_case_id=inherited_case.id,
                        is_local=(inherited_case.id == target_id),
                    )
                )

    # --- removed_entity_ids + removed_connections ----------------------------
    seen_entity_removals: set[str] = set()
    for inherited_case in chain:
        for entity_id in inherited_case.removed_entity_ids:
            if entity_id in seen_entity_removals:
                continue
            seen_entity_removals.add(entity_id)
            summary.removals.append(
                StructuralRemoval(
                    kind="entity",
                    payload=entity_id,
                    source_case_id=inherited_case.id,
                    is_local=(inherited_case.id == target_id),
                )
            )
        for conn in getattr(inherited_case, "removed_connections", []):
            key = tuple(conn)
            summary.removals.append(
                StructuralRemoval(
                    kind="connection",
                    payload=key,
                    source_case_id=inherited_case.id,
                    is_local=(inherited_case.id == target_id),
                )
            )

    # --- reference_overrides --------------------------------------------------
    # Track (entity_id, prop) -> (source, value, ancestor_set)
    ref_state: dict[tuple[str, str], tuple[str, Any, bool]] = {}
    for inherited_case in chain:
        for entity_id, overrides in inherited_case.reference_overrides.items():
            for prop, val in overrides.items():
                prior = ref_state.get((entity_id, prop))
                ancestor_set = prior is not None
                ref_state[(entity_id, prop)] = (inherited_case.id, val, ancestor_set or (prior is not None))
    for (entity_id, prop), (src_id, val, ancestor_set) in ref_state.items():
        is_local = src_id == target_id
        summary.reference_overrides.append(
            ReferenceOverride(
                entity_id=entity_id,
                prop=prop,
                value=val,
                source_case_id=src_id,
                is_local=is_local,
                shadows_inherited=is_local and ancestor_set,
            )
        )

    return summary
