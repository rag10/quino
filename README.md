8# QUINO — 2D Mechanism Modeling & Simulation Toolkit

QUINO is a library-first, extensible toolkit for creating, simulating, and analyzing 2D mechanisms. It combines a parametric model architecture with a professional GUI built on PySide6 and currently supports kinematic analysis via Exudyn.

## Vision

Build a platform-grade engineering application that:
- Prioritizes **library-first** architecture (GUI is optional)
- Treats **parametrization as a first-class citizen** from the start
- Supports **multiple solver backends** (currently Exudyn, extensible design)
- Maintains **clean separation** between domain, application, and UI layers
- Provides both **programmatic API** and **interactive GUI**

## Features (V1)

### Core Capabilities
- ✅ 2D mechanism modeling with bodies, markers, joints, and sliders
- ✅ Parametric expressions with unit support (mm, m, deg, rad, kg, s, etc.)
- ✅ Kinematic simulation via Exudyn backend
- ✅ Timeline playback and frame-by-frame analysis
- ✅ Full project persistence (JSON format: `.quino.json`)
- ✅ Undo/redo history

### Supported Mechanisms
- Four-bar linkage
- Slider-crank (connecting rod + slider)
- Custom mechanisms with revolute and rigid joints
- Ground connections and slider constraints

### GUI (PySide6)
- **Canvas**: Interactive 2D mechanism editor with pan/zoom
- **Tree View**: Hierarchical model structure
- **Inspector**: Property editing with expression evaluation
- **Parameters Panel**: Global parameter management
- **Timeline**: Simulation playback and frame control
- **Validation**: Real-time model checking
- **Professional UI**: Menu system, organized toolbar, custom SVG icons

## Installation

### From Source

```bash
# Clone and install
git clone https://github.com/rag10/quino.git
cd quino

# Install with GUI dependencies
pip install -e ".[gui]"

# Launch GUI
python -m quino.gui
# or
quino-gui
```

### Dependencies

**Core** (no external dependencies):
- Python ≥ 3.11

**GUI** (optional):
- PySide6 ≥ 6.6

**Solver** (optional):
- exudyn

**Development**:
- pytest ≥ 8.0
- ruff ≥ 0.5

## Quick Start

### Using the GUI

1. Launch the application: `quino-gui`
2. Create a new project: **File > New**
3. Load an example: **Examples > Load Four Bar** or **Load Slider Crank**
4. Edit the mechanism on the canvas, configure parameters, and run simulation
5. Play back results with the timeline controls

## Running An Analysis

1. Create or open a project.
2. Add a baseline or case in the workspace tree.
3. Add a workspace pose under that scope.
4. Right-click the pose and add an analysis.
5. For dynamic analyses, configure duration, frames, and `dt`.
6. Click `Run` in analysis mode.
7. Click a past run in the workflow tree to replay it.
8. Use `Plot` to save a plot recipe for that analysis.
9. Right-click a run and use `Export` workflows such as CSV or JSON.

The workflow tree now keeps a full run history per analysis, including notes, metrics, and persisted artefacts.

### Using the Library

```python
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput

# Initialize
app = ApplicationService()
app.new_project("MyMechanism")

# Create a bar (two-marker body)
bar_id = app.create_bar(
    "Crank",
    MarkerInput("0 mm", "0 mm", "A"),
    MarkerInput("50 mm", "0 mm", "B"),
)

# Create another body
link_id = app.create_body(
    "Link",
    [
        MarkerInput("0 mm", "0 mm", "C"),
        MarkerInput("80 mm", "0 mm", "D"),
    ],
)

# Create a ground joint
app.connect_marker_to_ground(
    next(m.id for m in app._find_body(bar_id).markers if m.name == "A"),
    joint_type="revolute",
    name="GroundA",
)

# Create a revolute joint between B and C
app.create_joint(
    "Joint1",
    "revolute",
    endpoint_a={"kind": "marker", "body_id": bar_id, "marker_id": "..."},
    endpoint_b={"kind": "marker", "body_id": link_id, "marker_id": "..."},
)

# Run simulation
result = app.run_kinematic_simulation(duration=1.0, steps=100)
print(f"Simulation success: {result.success}")
print(f"Frames: {len(result.frames)}")
```

## Architecture

```
┌─ Library (no Qt/solver dependencies) ─────────────┐
│  domain/          — Model entities (Body, Joint, etc.)
│  application/     — Use cases & commands
│  services/        — Units, expressions, validation
│  serialization/   — JSON I/O
│  simulation/      — Model assembly & translation
│  solver_adapters/ — Backend adapters (Exudyn, extensible)
└───────────────────────────────────────────────────┘
                        ↑
              ┌─────────┴─────────┐
              │                   │
        ┌─ GUI (optional) ────┐  │
        │ PySide6 + Canvas    │  │
        │ Toolbar, Inspector  │  │
        └─────────────────────┘  │
                                 │
          ┌───────────────────────┤
          │  Programmatic API     │
          │  (ApplicationService) │
          └───────────────────────┘
```

## Project Structure

```
quino/
├── src/quino/
│   ├── domain/          # Data models (Body, Marker, Joint, etc.)
│   ├── application/     # Application service & use cases
│   ├── services/        # Units, expressions, validation, IDs
│   ├── serialization/   # JSON read/write
│   ├── simulation/      # Assembly & solver translation
│   ├── solver_adapters/ # Backend adapters
│   └── gui/             # PySide6 interface (optional)
├── tests/               # Pytest suite
├── docs/                # Specification & documentation
├── pyproject.toml       # Package metadata & dependencies
└── README.md            # This file
```

## Testing

```bash
# Run all tests
pytest

# Run GUI tests specifically
pytest tests/test_gui.py -v

# Run with coverage
pytest --cov=src/quino tests/
```

All 9 GUI tests pass ✅

## Running an analysis

The workspace-driven analysis system lets you run dynamic / kinematic /
static / equilibrium studies against any pose. End-to-end walkthrough:

1. **Create a project** — `File → New` (or `python -m quino.gui` for a
   blank session).
2. **Add a workspace pose** under the active baseline or case. The
   pose is the configuration the analysis solves from.
3. **Add an analysis** under the pose with the type you want
   (`dynamic`, `kinematic`, `static`, or `equilibrium`).
4. **Configure parameters** in the bottom analysis panel — duration /
   steps / dt for dynamic, sweeps for kinematic, tolerance for static,
   perturbations for equilibrium.
5. **Click Run.** The background executor queues the run; a status
   strip shows queue depth and per-run progress, and you can cancel
   any time.
6. **Click a past run** in the workflow tree to replay it on the canvas
   from its persisted artefact.
7. **New plot** — `Analysis toolbar → New plot` opens the plot editor;
   plots are saved on the analysis and reopen with the project.
8. **Export** — right-click a run → `Export → CSV / JSON / matplotlib
   script` to dump the result artefact.

Right-clicking a case, baseline or the workspace root also gives
`Run all in case / Run baseline / Run workspace`, which enqueue every
analysis under that scope through the same executor.

## Analysis Types

The workspace-driven analysis system is described in:

- [Master plan](docs/superpowers/plans/2026-05-22-analysis-mode-master-plan.md)
- [Phase 1](docs/superpowers/plans/2026-05-22-phase-1-analysis-schema.md)
- [Phase 2](docs/superpowers/plans/2026-05-22-phase-2-background-executor.md)
- [Phase 3](docs/superpowers/plans/2026-05-22-phase-3-kinematic-infrastructure.md)
- [Phase 4](docs/superpowers/plans/2026-05-22-phase-4-static-equilibrium-solver.md)
- [Phase 5](docs/superpowers/plans/2026-05-22-phase-5-dynamic-mode-rewrite.md)
- [Phase 6](docs/superpowers/plans/2026-05-22-phase-6-kinematic-mode-ux.md)
- [Phase 7](docs/superpowers/plans/2026-05-22-phase-7-static-equilibrium-mode-ux.md)
- [Phase 8](docs/superpowers/plans/2026-05-22-phase-8-plots-metrics-compare.md)
- [Phase 9](docs/superpowers/plans/2026-05-22-phase-9-exports-batch-polish.md)

Open-ended follow-up ideas live in [docs/FUTURE_IDEAS.md](docs/FUTURE_IDEAS.md).

## Roadmap

- **V1 (current)**: 2D kinematics, parametric models, basic GUI
- **V2**: Dynamics, advanced constraints, more solver backends
- **V3**: Sketch layer, CAD-like constraint system, full 3D support (future)

## Design Principles

1. **Library-first**: GUI is a consumer of the core API, not vice versa
2. **No solver lock-in**: Domain model is independent of backends (Exudyn, Chrono, etc.)
3. **Parametrization from day one**: All geometric and kinematic properties support expressions
4. **JSON persistence**: Full project state serializable; versioned schema
5. **Type-safe**: Modern Python typing throughout
6. **Testable**: Core logic tested independently of GUI

## Contributing

Contributions are welcome. Please:
1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass and code passes `ruff` linting
5. Submit a pull request

## License

(License information to be added)

## References

Inspired by:
- [ASOM Kinematics](https://www.wm-kts.com/en/products/asom-kinematics/)
- [SAM Mechanism Designer](https://www.artas.nl/)
- [PMKS+](https://pmksprogram.com/)

---

**Status**: V1 Beta — Core functionality complete, GUI polished, ready for mechanism design workflows.
