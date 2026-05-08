from __future__ import annotations


class IdService:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def new(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}_{self._counters[prefix]:03d}"

    def observe(self, identifier: str) -> None:
        if "_" not in identifier:
            return
        prefix, suffix = identifier.rsplit("_", 1)
        if not suffix.isdigit():
            return
        self._counters[prefix] = max(self._counters.get(prefix, 0), int(suffix))
