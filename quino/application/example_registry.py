from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from quino.application.examples import build_four_bar_example, build_slider_crank_example
from quino.application.service import ApplicationService


@dataclass(frozen=True, slots=True)
class ExampleEntry:
    name: str
    description: str
    kind: str  # "builder" | "json"
    source: Callable[[ApplicationService], object] | str


class ExampleRegistry:
    """Central registry for built-in examples (code builders + JSON files)."""

    _BUILTINS: list[ExampleEntry] = [
        ExampleEntry(
            name="Four Bar",
            description="Classic four-bar linkage with crank, coupler and rocker",
            kind="builder",
            source=build_four_bar_example,
        ),
        ExampleEntry(
            name="Slider Crank",
            description="Slider-crank mechanism with crank, rod and guide",
            kind="builder",
            source=build_slider_crank_example,
        ),
    ]

    def __init__(self, examples_dir: str | Path | None = None) -> None:
        self._examples: list[ExampleEntry] = list(self._BUILTINS)
        self._discover_json_examples(examples_dir or Path("examples"))

    def _discover_json_examples(self, directory: str | Path) -> None:
        path = Path(directory)
        if not path.exists():
            return
        for json_file in sorted(path.glob("*.quino.json")):
            self._examples.append(
                ExampleEntry(
                    name=(json_file.stem[: -len(".quino")] if json_file.stem.endswith(".quino") else json_file.stem).replace("_", " "),
                    description=f"Open example from {json_file.name}",
                    kind="json",
                    source=str(json_file),
                )
            )

    def list_examples(self) -> list[ExampleEntry]:
        return list(self._examples)

    def load(self, app: ApplicationService, entry: ExampleEntry) -> None:
        if entry.kind == "builder":
            builder = entry.source
            if callable(builder):
                builder(app)
        elif entry.kind == "json":
            app.load_project(entry.source)
        else:
            raise ValueError(f"Unknown example kind: {entry.kind}")
