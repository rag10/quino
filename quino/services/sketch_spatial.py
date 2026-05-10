from __future__ import annotations

from quino.domain.sketch_evaluated import BBox


class SpatialIndex:
    """Simple brute-force spatial index for sketch entity bounding boxes."""

    def __init__(self) -> None:
        self._entries: dict[str, BBox] = {}

    def clear(self) -> None:
        self._entries.clear()

    def insert(self, entity_id: str, bbox: BBox) -> None:
        self._entries[entity_id] = bbox

    def remove(self, entity_id: str) -> None:
        self._entries.pop(entity_id, None)

    def query(self, bbox: BBox) -> list[str]:
        return [eid for eid, eb in self._entries.items() if eb.intersects(bbox)]

    def query_point(self, x: float, y: float) -> list[str]:
        return [eid for eid, eb in self._entries.items() if eb.contains(x, y)]
