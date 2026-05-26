from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
from quino.domain.plotting import MetricDef, PlotDef, YSeries
from quino.domain.workspace import (
    Analysis,
    ArtifactRef,
    Case,
    CaseOverlay,
    DynamicConfig,
    EntityOverlay,
    EquilibriumConfig,
    KinematicConfig,
    MetricDefinition,
    ParameterDescriptor,
    Pose,
    ResultRef,
    Run,
    ScalarValue,
    StaticConfig,
    SweepDef,
    Tolerance,
    Workspace,
)
from quino.domain.model import (
    Body,
    BodyPose,
    CoMAnchor,
    Driver,
    Expression,
    GravityLoad,
    Joint,
    JointEndpoint,
    Load,
    Marker,
    Metadata,
    Model,
    Parameter,
    ReactionOutput,
    ScalarProperty,
    Sensor,
    SensorOutput,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    SketchSpline,
    Slider,
    Spring,
    SpringEndpoint,
    Style,
    Variable,
    ViewState,
)
from quino.domain.types import (
    BodyType,
    Dimension,
    DriverType,
    JointEndpointKind,
    JointType,
    MarkerType,
    SensorType,
    SketchEntityType,
    SketchConstraintType,
    SpringEndpointKind,
    SpringType,
)


class UnsupportedSchemaError(ValueError):
    """Raised when a JSON file has a schema version other than 0.3.0."""


class JsonMapper:
    # ------------------------------------------------------------------
    # Public API — schema 0.3.0 Workspace
    # ------------------------------------------------------------------

    def save(self, workspace: Workspace, path: str | Path) -> None:
        """Serialise *workspace* to *path* as JSON."""
        data = self._workspace_to_dict(workspace)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)

    def load(self, path: str | Path) -> Workspace:
        """Load a schema 0.3.0 workspace from *path*.

        Raises ``UnsupportedSchemaError`` for any other schema version.
        """
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        version = data.get("schema_version")
        if version != "0.3.0":
            raise UnsupportedSchemaError(
                f"This file uses schema version {version!r}. "
                f"Only schema 0.3.0 is supported by this reader."
            )
        return self._workspace_from_dict(data)

    # ------------------------------------------------------------------
    # Workspace top-level
    # ------------------------------------------------------------------

    def _workspace_to_dict(self, ws: Workspace) -> dict:
        return {
            "schema_version": ws.schema_version,
            "id": ws.id,
            "name": ws.name,
            "sketch": self._sketch_to_dict(ws.sketch) if ws.sketch else None,
            "parameters": [self._parameter_to_dict(p) for p in ws.parameters],
            "parameter_catalog": {
                k: self._parameter_descriptor_to_dict(v)
                for k, v in ws.parameter_catalog.items()
            },
            "view_state": self._view_state_to_dict(ws.view_state),
            "gravity_default": (
                self._gravity_to_dict(ws.gravity_default)
                if ws.gravity_default is not None
                else None
            ),
            "root_case_ids": list(ws.root_case_ids),
            "cases": {cid: self._case_to_dict(c) for cid, c in ws.cases.items()},
            "selected_case_id": ws.selected_case_id,
            "selected_pose_id": ws.selected_pose_id,
            "selected_analysis_id": ws.selected_analysis_id,
            "metadata": dict(ws.metadata),
        }

    def _workspace_from_dict(self, data: dict) -> Workspace:
        ws = Workspace(
            id=data["id"],
            name=data["name"],
            schema_version=data["schema_version"],
            sketch=self._sketch_from_dict(data.get("sketch")),
            parameters=[self._parameter_from_dict(p) for p in data.get("parameters", [])],
            parameter_catalog={
                k: self._parameter_descriptor_from_dict(v)
                for k, v in data.get("parameter_catalog", {}).items()
            },
            view_state=self._view_state_from_dict(data.get("view_state", {})),
            gravity_default=(
                self._gravity_from_dict(data["gravity_default"])
                if data.get("gravity_default")
                else None
            ),
            root_case_ids=list(data.get("root_case_ids", [])),
            selected_case_id=data.get("selected_case_id"),
            selected_pose_id=data.get("selected_pose_id"),
            selected_analysis_id=data.get("selected_analysis_id"),
            metadata=dict(data.get("metadata", {})),
        )
        for cid, cdata in data.get("cases", {}).items():
            ws.cases[cid] = self._case_from_dict(cdata)
        return ws

    # ------------------------------------------------------------------
    # Case
    # ------------------------------------------------------------------

    def _case_to_dict(self, c: Case) -> dict:
        result: dict[str, Any] = {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "parent_case_id": c.parent_case_id,
            "model": self._model_to_dict(c.model),
            "poses": [self._pose_to_dict(p) for p in c.poses],
            "analyses": [self._analysis_to_dict(a) for a in c.analyses],
            "runs": [self._run_to_dict(r) for r in c.runs],
            "overlay": self._overlay_to_dict(c.overlay) if c.overlay is not None else None,
            "tolerances": {k: self._tolerance_to_dict(v) for k, v in c.tolerances.items()},
            "metrics": {k: self._metric_definition_to_dict(v) for k, v in c.metrics.items()},
            "metadata": dict(c.metadata),
        }
        if c.sensor_outputs:
            result["sensor_outputs"] = {
                k: self._sensor_output_to_dict(v) for k, v in c.sensor_outputs.items()
            }
        if c.reaction_outputs:
            result["reaction_outputs"] = {
                k: self._reaction_output_to_dict(v) for k, v in c.reaction_outputs.items()
            }
        return result

    def _case_from_dict(self, data: dict) -> Case:
        return Case(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            parent_case_id=data.get("parent_case_id"),
            model=self._model_from_dict(data.get("model", {})),
            poses=[self._pose_from_dict(p) for p in data.get("poses", [])],
            analyses=[self._analysis_from_dict(a) for a in data.get("analyses", [])],
            runs=[self._run_from_dict(r) for r in data.get("runs", [])],
            sensor_outputs={
                k: self._sensor_output_from_dict(v)
                for k, v in data.get("sensor_outputs", {}).items()
            },
            reaction_outputs={
                k: self._reaction_output_from_dict(v)
                for k, v in data.get("reaction_outputs", {}).items()
            },
            overlay=(
                self._overlay_from_dict(data["overlay"])
                if data.get("overlay") is not None
                else None
            ),
            tolerances={
                k: self._tolerance_from_dict(v)
                for k, v in data.get("tolerances", {}).items()
            },
            metrics={
                k: self._metric_definition_from_dict(v)
                for k, v in data.get("metrics", {}).items()
            },
            metadata=dict(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # CaseOverlay / EntityOverlay
    # ------------------------------------------------------------------

    def _overlay_to_dict(self, o: CaseOverlay) -> dict:
        return {
            "entities": {
                k: {"origin": v.origin, "linked_properties": sorted(v.linked_properties)}
                for k, v in o.entities.items()
            },
            "deleted_inherited_entity_ids": sorted(o.deleted_inherited_entity_ids),
            "inherited_connections": [
                list(t) for t in sorted(o.inherited_connections)
            ],
            "deleted_inherited_connections": [
                list(t) for t in sorted(o.deleted_inherited_connections)
            ],
            "poses": {
                k: {"origin": v.origin, "linked_properties": sorted(v.linked_properties)}
                for k, v in o.poses.items()
            },
            "deleted_inherited_pose_ids": sorted(o.deleted_inherited_pose_ids),
        }

    def _overlay_from_dict(self, data: dict) -> CaseOverlay:
        return CaseOverlay(
            entities={
                k: EntityOverlay(
                    origin=v["origin"],
                    linked_properties=set(v.get("linked_properties", [])),
                )
                for k, v in data.get("entities", {}).items()
            },
            deleted_inherited_entity_ids=set(data.get("deleted_inherited_entity_ids", [])),
            inherited_connections={
                tuple(t) for t in data.get("inherited_connections", [])
            },
            deleted_inherited_connections={
                tuple(t) for t in data.get("deleted_inherited_connections", [])
            },
            poses={
                k: EntityOverlay(
                    origin=v["origin"],
                    linked_properties=set(v.get("linked_properties", [])),
                )
                for k, v in data.get("poses", {}).items()
            },
            deleted_inherited_pose_ids=set(data.get("deleted_inherited_pose_ids", [])),
        )

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------

    def _model_to_dict(self, model: Model) -> dict:
        result: dict[str, Any] = {
            "bodies": [self._body_to_dict(b) for b in model.bodies],
            "sliders": [self._slider_to_dict(s) for s in model.sliders],
            "joints": [self._joint_to_dict(j) for j in model.joints],
            "drivers": [self._driver_to_dict(d) for d in model.drivers],
            "loads": [self._load_to_dict(lo) for lo in model.loads],
            "sensors": [self._sensor_to_dict(s) for s in model.sensors],
            "springs": [self._spring_to_dict(sp) for sp in model.springs],
            "gravity": (
                {
                    "magnitude": model.gravity.magnitude,
                    "direction_x": model.gravity.direction_x,
                    "direction_y": model.gravity.direction_y,
                }
                if model.gravity is not None
                else None
            ),
        }
        if model.control_graph is not None and model.control_graph.instances:
            result["control_graph"] = self._block_diagram_to_dict(model.control_graph)
        return result

    def _model_from_dict(self, data: dict) -> Model:
        return Model(
            bodies=[self._body_from_dict(item) for item in data.get("bodies", [])],
            sliders=[self._slider_from_dict(item) for item in data.get("sliders", [])],
            joints=[self._joint_from_dict(item) for item in data.get("joints", [])],
            drivers=[self._driver_from_dict(item) for item in data.get("drivers", [])],
            loads=[self._load_from_dict(item) for item in data.get("loads", [])],
            sensors=[self._sensor_from_dict(item) for item in data.get("sensors", [])],
            springs=[self._spring_from_dict(item) for item in data.get("springs", [])],
            gravity=self._gravity_from_dict(data.get("gravity")),
            control_graph=self._block_diagram_from_dict(data.get("control_graph")),
        )

    # ------------------------------------------------------------------
    # Pose (workspace-level — quino.domain.workspace.Pose)
    # ------------------------------------------------------------------

    def _pose_to_dict(self, pose: Pose | None) -> dict | None:
        if pose is None:
            return None
        result: dict = {
            "id": pose.id,
            "name": pose.name,
            "body_poses": {
                body_id: self._body_pose_to_dict(bp)
                for body_id, bp in pose.body_poses.items()
            },
            "parent_pose_id": pose.parent_pose_id,
            "is_default": pose.is_default,
            "requires_recompute": pose.requires_recompute,
            "solve_failed": pose.solve_failed,
            "metadata": pose.metadata.values,
        }
        if pose.initial_velocities:
            result["initial_velocities"] = dict(pose.initial_velocities)
        return result

    def _pose_from_dict(self, data: dict | None) -> Pose | None:
        if data is None:
            return None
        return Pose(
            id=data["id"],
            name=data["name"],
            body_poses={
                body_id: self._body_pose_from_dict(bp)
                for body_id, bp in data.get("body_poses", {}).items()
            },
            initial_velocities={
                str(k): float(v)
                for k, v in data.get("initial_velocities", {}).items()
            },
            parent_pose_id=data.get("parent_pose_id"),
            is_default=data.get("is_default", False),
            requires_recompute=data.get("requires_recompute", True),
            solve_failed=data.get("solve_failed", False),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _analysis_to_dict(self, analysis: Analysis) -> dict:
        return {
            "id": analysis.id,
            "name": analysis.name,
            "analysis_type": analysis.analysis_type,
            "pose_id": analysis.pose_id,
            "config": self._analysis_config_to_dict(analysis.analysis_type, analysis.config),
            "metadata": dict(analysis.metadata),
        }

    def _analysis_config_to_dict(self, kind: str, cfg) -> dict:
        from dataclasses import asdict
        return asdict(cfg)

    def _analysis_from_dict(self, data: dict) -> Analysis:
        kind = data.get("analysis_type", "dynamic")
        cfg = self._analysis_config_from_dict(kind, data.get("config") or {})
        return Analysis(
            id=data["id"],
            name=data["name"],
            analysis_type=kind,
            pose_id=data.get("pose_id"),
            config=cfg,
            metadata=dict(data.get("metadata", {})),
        )

    def _analysis_config_from_dict(self, kind: str, data: dict):
        plots = [self._plot_def_from_dict(item) for item in data.get("plots", [])]
        metrics = [self._metric_def_from_dict(item) for item in data.get("metrics", [])]
        if kind == "dynamic":
            return DynamicConfig(
                **{k: v for k, v in data.items() if k in {"duration", "steps", "dt", "integrator", "solver_settings"}},
                plots=plots,
                metrics=metrics,
            )
        if kind == "kinematic":
            sweeps = [SweepDef(**s) for s in data.get("sweeps", [])]
            return KinematicConfig(
                sweeps=sweeps,
                allow_failed_steps=data.get("allow_failed_steps", True),
                plots=plots,
                metrics=metrics,
            )
        if kind == "static":
            return StaticConfig(
                **{
                    k: v
                    for k, v in data.items()
                    if k in {"gravity_enabled", "tolerance", "report_reactions", "report_spring_energy"}
                },
                plots=plots,
                metrics=metrics,
            )
        if kind == "equilibrium":
            return EquilibriumConfig(
                **{
                    k: v
                    for k, v in data.items()
                    if k in {"gravity_enabled", "initial_perturbations", "stability_check", "pose_match_tolerance"}
                },
                plots=plots,
                metrics=metrics,
            )
        raise ValueError(f"Unknown analysis_type {kind!r}")

    def _y_series_from_dict(self, data: dict) -> YSeries:
        return YSeries(
            sensor_id=data["sensor_id"],
            channel=data.get("channel", ""),
            label=data.get("label", ""),
            color=data.get("color", ""),
        )

    def _plot_def_from_dict(self, data: dict) -> PlotDef:
        return PlotDef(
            id=data["id"],
            title=data["title"],
            x_kind=data.get("x_kind", "time"),
            x_target=data.get("x_target", ""),
            y_series=[self._y_series_from_dict(item) for item in data.get("y_series", [])],
            style=dict(data.get("style", {})),
        )

    def _metric_def_from_dict(self, data: dict) -> MetricDef:
        return MetricDef(
            id=data["id"],
            key=data["key"],
            name=data["name"],
            kind=data.get("kind", "max"),
            target=data.get("target", ""),
            params=dict(data.get("params", {})),
            tags=list(data.get("tags", [])),
        )

    # ------------------------------------------------------------------
    # Run / artifacts
    # ------------------------------------------------------------------

    def _run_to_dict(self, run: Run) -> dict:
        out: dict[str, Any] = {
            "id": run.id,
            "analysis_id": run.analysis_id,
            "created_at": run.created_at,
            "finished_at": run.finished_at,
            "status": run.status,
            "note": run.note,
            "metrics": dict(run.metrics),
            "warnings": list(run.warnings),
            "error_message": run.error_message,
            "config_snapshot": dict(run.config_snapshot),
        }
        if run.result_ref is not None:
            out["result_ref"] = self._result_ref_to_dict(run.result_ref)
        if run.artifacts:
            out["artifacts"] = [self._artifact_ref_to_dict(a) for a in run.artifacts]
        return out

    def _run_from_dict(self, data: dict) -> Run:
        return Run(
            id=data["id"],
            analysis_id=data["analysis_id"],
            created_at=data["created_at"],
            finished_at=data.get("finished_at"),
            status=data.get("status", "to_be_run"),
            note=data.get("note", ""),
            result_ref=(
                self._result_ref_from_dict(data["result_ref"])
                if data.get("result_ref")
                else None
            ),
            artifacts=[self._artifact_ref_from_dict(a) for a in data.get("artifacts", [])],
            metrics=dict(data.get("metrics", {})),
            warnings=list(data.get("warnings", [])),
            error_message=data.get("error_message", ""),
            config_snapshot=dict(data.get("config_snapshot", {})),
        )

    def _result_ref_to_dict(self, ref: ResultRef) -> dict:
        return {
            "run_entry_id": ref.run_entry_id,
            "artifact_path": ref.artifact_path,
            "checksum": ref.checksum,
        }

    def _result_ref_from_dict(self, data: dict) -> ResultRef:
        return ResultRef(
            run_entry_id=data["run_entry_id"],
            artifact_path=data["artifact_path"],
            checksum=data["checksum"],
        )

    def _artifact_ref_to_dict(self, ref: ArtifactRef) -> dict:
        return {
            "kind": ref.kind,
            "path": ref.path,
            "checksum": ref.checksum,
            "metadata": ref.metadata,
        }

    def _artifact_ref_from_dict(self, data: dict) -> ArtifactRef:
        return ArtifactRef(
            kind=data["kind"],
            path=data["path"],
            checksum=data.get("checksum", ""),
            metadata=data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # SensorOutput / ReactionOutput
    # ------------------------------------------------------------------

    def _sensor_output_to_dict(self, so: SensorOutput) -> dict:
        return {
            "sensor_id": so.sensor_id,
            "time": list(so.time),
            "columns": list(so.columns),
            "data": [list(row) for row in so.data],
        }

    def _sensor_output_from_dict(self, data: dict) -> SensorOutput:
        return SensorOutput(
            sensor_id=data["sensor_id"],
            time=list(data.get("time", [])),
            columns=list(data.get("columns", [])),
            data=[list(row) for row in data.get("data", [])],
        )

    def _reaction_output_to_dict(self, ro: ReactionOutput) -> dict:
        return {
            "joint_id": ro.joint_id,
            "joint_name": ro.joint_name,
            "endpoint_type": ro.endpoint_type,
            "time": list(ro.time),
            "columns": list(ro.columns),
            "data": [list(row) for row in ro.data],
            "positions": [list(p) for p in ro.positions],
        }

    def _reaction_output_from_dict(self, data: dict) -> ReactionOutput:
        return ReactionOutput(
            joint_id=data["joint_id"],
            joint_name=data["joint_name"],
            endpoint_type=data["endpoint_type"],
            time=list(data.get("time", [])),
            columns=list(data.get("columns", [])),
            data=[list(row) for row in data.get("data", [])],
            positions=[tuple(p) for p in data.get("positions", [])],
        )

    # ------------------------------------------------------------------
    # Tolerance / MetricDefinition / ParameterDescriptor / ScalarValue
    # ------------------------------------------------------------------

    def _tolerance_to_dict(self, tolerance: Tolerance) -> dict:
        result: dict = {"metric_key": tolerance.metric_key}
        if tolerance.absolute is not None:
            result["absolute"] = tolerance.absolute
        if tolerance.relative is not None:
            result["relative"] = tolerance.relative
        return result

    def _tolerance_from_dict(self, data: dict) -> Tolerance:
        return Tolerance(
            metric_key=data["metric_key"],
            absolute=data.get("absolute"),
            relative=data.get("relative"),
        )

    def _metric_definition_to_dict(self, metric: MetricDefinition) -> dict:
        return {
            "key": metric.key,
            "name": metric.name,
            "extractor": metric.extractor,
            "unit": metric.unit,
        }

    def _metric_definition_from_dict(self, data: dict) -> MetricDefinition:
        return MetricDefinition(
            key=data["key"],
            name=data["name"],
            extractor=data["extractor"],
            unit=data.get("unit", ""),
        )

    def _parameter_descriptor_to_dict(self, descriptor: ParameterDescriptor) -> dict:
        return {
            "path": descriptor.path,
            "tag": descriptor.tag,
            "display_name": descriptor.display_name,
            "unit": descriptor.unit,
            "dimension": descriptor.dimension,
            "default_value": descriptor.default_value,
            "entity_id": descriptor.entity_id,
            "property_name": descriptor.property_name,
        }

    def _parameter_descriptor_from_dict(self, data: dict) -> ParameterDescriptor:
        return ParameterDescriptor(
            path=data["path"],
            tag=data.get("tag", "invariant"),
            display_name=data.get("display_name", ""),
            unit=data.get("unit", ""),
            dimension=data.get("dimension", ""),
            default_value=data.get("default_value"),
            entity_id=data.get("entity_id"),
            property_name=data.get("property_name"),
        )

    def _scalar_value_to_dict(self, value: ScalarValue) -> dict:
        return {"value": value.value, "unit": value.unit}

    def _scalar_value_from_dict(self, data: dict) -> ScalarValue:
        return ScalarValue(value=float(data["value"]), unit=data.get("unit", ""))

    # ------------------------------------------------------------------
    # ViewState / gravity
    # ------------------------------------------------------------------

    def _view_state_to_dict(self, vs: ViewState) -> dict:
        return {
            "zoom": vs.zoom,
            "pan_x": vs.pan_x,
            "pan_y": vs.pan_y,
            "show_grid": vs.show_grid,
            "show_sensors": vs.show_sensors,
            "show_markers": vs.show_markers,
            "show_com": vs.show_com,
            "show_sliders": vs.show_sliders,
        }

    def _view_state_from_dict(self, data: dict) -> ViewState:
        return ViewState(**{k: v for k, v in data.items() if k in {
            "zoom", "pan_x", "pan_y", "show_grid",
            "show_sensors", "show_markers", "show_com", "show_sliders",
        }})

    def _gravity_to_dict(self, g: GravityLoad) -> dict:
        return {
            "magnitude": g.magnitude,
            "direction_x": g.direction_x,
            "direction_y": g.direction_y,
        }

    def _gravity_from_dict(self, data: dict | None) -> GravityLoad | None:
        if data is None:
            return None
        if not data.get("enabled", True):
            return None
        return GravityLoad(
            magnitude=data.get("magnitude", 9.81),
            direction_x=data.get("direction_x", 0.0),
            direction_y=data.get("direction_y", -1.0),
        )

    # ------------------------------------------------------------------
    # Parameter
    # ------------------------------------------------------------------

    def _parameter_to_dict(self, parameter: Parameter) -> dict:
        return {
            "id": parameter.id,
            "name": parameter.name,
            "expression": parameter.expression,
            "unit": parameter.unit,
            "description": parameter.description,
            "metadata": parameter.metadata.values,
        }

    def _parameter_from_dict(self, data: dict) -> Parameter:
        return Parameter(
            id=data["id"],
            name=data["name"],
            expression=data["expression"],
            unit=data["unit"],
            description=data.get("description", ""),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # BodyPose
    # ------------------------------------------------------------------

    def _body_pose_to_dict(self, body_pose: BodyPose) -> dict:
        return {
            "body_id": body_pose.body_id,
            "x": body_pose.x,
            "y": body_pose.y,
            "angle": body_pose.angle,
        }

    def _body_pose_from_dict(self, data: dict) -> BodyPose:
        return BodyPose(
            body_id=data["body_id"],
            x=float(data["x"]),
            y=float(data["y"]),
            angle=float(data["angle"]),
        )

    # ------------------------------------------------------------------
    # ScalarProperty / Expression
    # ------------------------------------------------------------------

    def _scalar_to_dict(self, value: ScalarProperty | None) -> dict | None:
        if value is None:
            return None
        return {
            "expression": value.expression,
            "unit": value.unit,
            "expected_dimension": value.expected_dimension.value,
        }

    def _scalar_from_dict(self, data: dict | None) -> ScalarProperty | None:
        if data is None:
            return None
        return ScalarProperty(
            expression=data["expression"],
            unit=data["unit"],
            expected_dimension=Dimension(data["expected_dimension"]),
        )

    def _expression_to_dict(self, value: Expression | None) -> dict | None:
        if value is None:
            return None
        return {"text": value.text, "unit": value.unit}

    def _expression_from_dict(self, data: dict | None) -> Expression | None:
        if data is None:
            return None
        if "text" in data:
            return Expression(text=data["text"], unit=data.get("unit", "mm"))
        return Expression(text=data.get("expression", ""), unit=data.get("unit", "mm"))

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _style_to_dict(self, style: Style) -> dict:
        return {
            "color": style.color,
            "visible": style.visible,
            "line_width": style.line_width,
            "marker_size": style.marker_size,
        }

    def _style_from_dict(self, data: dict | None) -> Style:
        if data is None:
            return Style()
        return Style(**data)

    # ------------------------------------------------------------------
    # Marker / Body
    # ------------------------------------------------------------------

    def _marker_to_dict(self, marker: Marker) -> dict:
        return {
            "id": marker.id,
            "name": marker.name,
            "type": marker.type.value,
            "x": self._scalar_to_dict(marker.x),
            "y": self._scalar_to_dict(marker.y),
            "visible": marker.visible,
            "style": self._style_to_dict(marker.style),
            "metadata": marker.metadata.values,
        }

    def _marker_from_dict(self, data: dict) -> Marker:
        return Marker(
            id=data["id"],
            name=data["name"],
            type=MarkerType(data["type"]),
            x=self._scalar_from_dict(data["x"]),
            y=self._scalar_from_dict(data["y"]),
            visible=data.get("visible", True),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _body_to_dict(self, body: Body) -> dict:
        structural = [m for m in body.markers if m.type is MarkerType.STRUCTURAL]
        return {
            "id": body.id,
            "name": body.name,
            "type": body.type.value,
            "markers": [self._marker_to_dict(marker) for marker in structural],
            "edge_order": body.edge_order,
            "closed_shape": body.closed_shape,
            "mass": self._scalar_to_dict(body.mass),
            "com": {"kind": body.com.kind, "data": dict(body.com.data)},
            "style": self._style_to_dict(body.style),
            "metadata": body.metadata.values,
        }

    def _body_from_dict(self, data: dict) -> Body:
        raw_markers = [self._marker_from_dict(item) for item in data.get("markers", [])]
        structural = [m for m in raw_markers if m.type is MarkerType.STRUCTURAL]
        com_payload = data.get("com")
        if com_payload is None:
            body_type = BodyType(data["type"])
            if body_type is BodyType.POINT_MASS and len(structural) == 1:
                anchor = CoMAnchor(kind="marker", data={"marker_id": structural[0].id})
            elif body_type is BodyType.BAR and len(structural) == 2:
                legacy_com = next(
                    (m for m in raw_markers if m.type is not MarkerType.STRUCTURAL), None,
                )
                percent = 50.0
                if legacy_com is not None:
                    try:
                        percent = float(legacy_com.metadata.values.get("position_percent", 50.0))
                    except (TypeError, ValueError):
                        percent = 50.0
                anchor = CoMAnchor(kind="bar_percent", data={"percent": percent})
            else:
                anchor = CoMAnchor(
                    kind="barycentric",
                    data={"weights": {m.id: 1.0 for m in structural}},
                )
        else:
            anchor = CoMAnchor(
                kind=str(com_payload.get("kind", "local_offset")),
                data=dict(com_payload.get("data", {})),
            )
        return Body(
            id=data["id"],
            name=data["name"],
            type=BodyType(data["type"]),
            markers=structural,
            edge_order=data.get("edge_order", []),
            closed_shape=data.get("closed_shape", True),
            mass=self._scalar_from_dict(data.get("mass")),
            com=anchor,
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Slider
    # ------------------------------------------------------------------

    def _slider_to_dict(self, slider: Slider) -> dict:
        return {
            "id": slider.id,
            "name": slider.name,
            "origin_x": self._scalar_to_dict(slider.origin_x),
            "origin_y": self._scalar_to_dict(slider.origin_y),
            "angle": self._scalar_to_dict(slider.angle),
            "travel_min": self._scalar_to_dict(slider.travel_min),
            "travel_max": self._scalar_to_dict(slider.travel_max),
            "style": self._style_to_dict(slider.style),
            "metadata": slider.metadata.values,
        }

    def _slider_from_dict(self, data: dict) -> Slider:
        return Slider(
            id=data["id"],
            name=data["name"],
            origin_x=self._scalar_from_dict(data["origin_x"]),
            origin_y=self._scalar_from_dict(data["origin_y"]),
            angle=self._scalar_from_dict(data["angle"]),
            travel_min=self._scalar_from_dict(data.get("travel_min")),
            travel_max=self._scalar_from_dict(data.get("travel_max")),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Joint
    # ------------------------------------------------------------------

    def _endpoint_to_dict(self, endpoint: JointEndpoint) -> dict:
        result = {"kind": endpoint.kind.value}
        if endpoint.body_id is not None:
            result["body_id"] = endpoint.body_id
        if endpoint.marker_id is not None:
            result["marker_id"] = endpoint.marker_id
        if endpoint.slider_id is not None:
            result["slider_id"] = endpoint.slider_id
        return result

    def _endpoint_from_dict(self, data: dict) -> JointEndpoint:
        return JointEndpoint(
            kind=JointEndpointKind(data["kind"]),
            body_id=data.get("body_id"),
            marker_id=data.get("marker_id"),
            slider_id=data.get("slider_id"),
        )

    def _joint_to_dict(self, joint: Joint) -> dict:
        return {
            "id": joint.id,
            "name": joint.name,
            "type": joint.type.value,
            "endpoint_a": self._endpoint_to_dict(joint.endpoint_a),
            "endpoint_b": self._endpoint_to_dict(joint.endpoint_b),
            "style": self._style_to_dict(joint.style),
            "metadata": joint.metadata.values,
        }

    def _joint_from_dict(self, data: dict) -> Joint:
        return Joint(
            id=data["id"],
            name=data["name"],
            type=JointType(data["type"]),
            endpoint_a=self._endpoint_from_dict(data["endpoint_a"]),
            endpoint_b=self._endpoint_from_dict(data["endpoint_b"]),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def _driver_to_dict(self, driver: Driver) -> dict:
        return {
            "id": driver.id,
            "name": driver.name,
            "type": driver.type.value,
            "target_joint_id": driver.target_joint_id,
            "law": self._scalar_to_dict(driver.law),
            "metadata": driver.metadata.values,
        }

    def _driver_from_dict(self, data: dict) -> Driver:
        return Driver(
            id=data["id"],
            name=data["name"],
            type=DriverType(data["type"]),
            target_joint_id=data["target_joint_id"],
            law=self._scalar_from_dict(data["law"]),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _load_to_dict(self, load: Load) -> dict:
        return {
            "id": load.id,
            "name": load.name,
            "target_marker_id": load.target_marker_id,
            "fx": self._scalar_to_dict(load.fx),
            "fy": self._scalar_to_dict(load.fy),
            "metadata": load.metadata.values,
        }

    def _load_from_dict(self, data: dict) -> Load:
        return Load(
            id=data["id"],
            name=data["name"],
            target_marker_id=data["target_marker_id"],
            fx=self._scalar_from_dict(data["fx"]),
            fy=self._scalar_from_dict(data["fy"]),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Sensor
    # ------------------------------------------------------------------

    def _sensor_to_dict(self, sensor: Sensor) -> dict:
        return {
            "id": sensor.id,
            "name": sensor.name,
            "type": sensor.type.value,
            "marker_ids": sensor.marker_ids,
            "metadata": sensor.metadata.values,
        }

    def _sensor_from_dict(self, data: dict) -> Sensor:
        return Sensor(
            id=data["id"],
            name=data["name"],
            type=SensorType(data["type"]),
            marker_ids=data.get("marker_ids", []),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Spring
    # ------------------------------------------------------------------

    def _spring_endpoint_to_dict(self, ep: SpringEndpoint) -> dict:
        result: dict = {"kind": ep.kind.value}
        if ep.body_id is not None:
            result["body_id"] = ep.body_id
        if ep.marker_id is not None:
            result["marker_id"] = ep.marker_id
        if ep.ground_x is not None:
            result["ground_x"] = self._scalar_to_dict(ep.ground_x)
        if ep.ground_y is not None:
            result["ground_y"] = self._scalar_to_dict(ep.ground_y)
        return result

    def _spring_endpoint_from_dict(self, data: dict) -> SpringEndpoint:
        return SpringEndpoint(
            kind=SpringEndpointKind(data["kind"]),
            body_id=data.get("body_id"),
            marker_id=data.get("marker_id"),
            ground_x=self._scalar_from_dict(data.get("ground_x")),
            ground_y=self._scalar_from_dict(data.get("ground_y")),
        )

    def _spring_to_dict(self, spring: Spring) -> dict:
        return {
            "id": spring.id,
            "name": spring.name,
            "spring_type": spring.spring_type.value,
            "endpoint_a": self._spring_endpoint_to_dict(spring.endpoint_a),
            "endpoint_b": self._spring_endpoint_to_dict(spring.endpoint_b),
            "rest_value": self._scalar_to_dict(spring.rest_value),
            "law": self._scalar_to_dict(spring.law),
            "style": self._style_to_dict(spring.style),
            "metadata": spring.metadata.values,
        }

    def _spring_from_dict(self, data: dict) -> Spring:
        return Spring(
            id=data["id"],
            name=data["name"],
            spring_type=SpringType(data["spring_type"]),
            endpoint_a=self._spring_endpoint_from_dict(data["endpoint_a"]),
            endpoint_b=self._spring_endpoint_from_dict(data["endpoint_b"]),
            rest_value=self._scalar_from_dict(data.get("rest_value")),
            law=self._scalar_from_dict(data.get("law")),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Sketch
    # ------------------------------------------------------------------

    def _sketch_to_dict(self, sketch: Sketch | None) -> dict | None:
        if sketch is None:
            return None
        return {
            "id": sketch.id,
            "name": sketch.name,
            "visible": sketch.visible,
            "style": self._style_to_dict(sketch.style),
            "entities": {
                eid: self._sketch_entity_to_dict(entity)
                for eid, entity in sketch.entities.items()
            },
            "constraints": {
                cid: self._sketch_constraint_to_dict(constraint)
                for cid, constraint in sketch.constraints.items()
            },
            "variables": {
                vid: self._variable_to_dict(variable)
                for vid, variable in sketch.variables.items()
            },
            "metadata": sketch.metadata.values,
        }

    def _sketch_from_dict(self, data: dict | None) -> Sketch | None:
        if data is None:
            return None
        entities_data = data.get("entities", {})
        constraints_data = data.get("constraints", {})
        variables_data = data.get("variables", {})
        if isinstance(entities_data, list):
            entities_data = {item["id"]: item for item in entities_data}
        if isinstance(constraints_data, list):
            constraints_data = {item["id"]: item for item in constraints_data}
        if isinstance(variables_data, list):
            variables_data = {item["name"]: item for item in variables_data}
        return Sketch(
            id=data["id"],
            name=data["name"],
            visible=data.get("visible", True),
            style=self._style_from_dict(data.get("style")),
            entities={
                eid: self._sketch_entity_from_dict(item)
                for eid, item in entities_data.items()
            },
            constraints={
                cid: self._sketch_constraint_from_dict(item)
                for cid, item in constraints_data.items()
            },
            variables={
                vid: self._variable_from_dict(item)
                for vid, item in variables_data.items()
            },
            metadata=Metadata(data.get("metadata", {})),
        )

    def _variable_to_dict(self, variable: Variable) -> dict:
        return {"name": variable.name, "expression": variable.expression}

    def _variable_from_dict(self, data: dict) -> Variable:
        return Variable(name=data["name"], expression=data["expression"])

    def _sketch_constraint_to_dict(self, constraint: SketchConstraint) -> dict:
        return {
            "id": constraint.id,
            "name": constraint.name,
            "type": constraint.type.value,
            "references": list(constraint.references),
            "value": (
                self._scalar_to_dict(constraint.value)
                if constraint.value is not None
                else None
            ),
            "entity_references": list(constraint.entity_references),
            "enabled": constraint.enabled,
            "driving": constraint.driving,
            "metadata": constraint.metadata.values,
        }

    def _sketch_constraint_from_dict(self, data: dict) -> SketchConstraint:
        return SketchConstraint(
            id=data["id"],
            name=data["name"],
            type=SketchConstraintType(data["type"]),
            references=list(data.get("references", [])),
            value=(
                self._scalar_from_dict(data["value"])
                if data.get("value") is not None
                else None
            ),
            entity_references=list(data.get("entity_references", [])),
            enabled=data.get("enabled", True),
            driving=data.get("driving", True),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _sketch_entity_to_dict(
        self,
        entity: SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline,
    ) -> dict:
        base = {
            "id": entity.id,
            "name": entity.name,
            "type": entity.type.value,
            "visible": entity.visible,
            "construction": entity.construction,
            "selectable": entity.selectable,
            "style": self._style_to_dict(entity.style),
            "metadata": entity.metadata.values,
        }
        if isinstance(entity, SketchPoint):
            base["x"] = self._expression_to_dict(entity.x)
            base["y"] = self._expression_to_dict(entity.y)
        elif isinstance(entity, SketchLineSegment):
            base["start_point_id"] = entity.start_point_id
            base["end_point_id"] = entity.end_point_id
        elif isinstance(entity, SketchCircle):
            base["center_point_id"] = entity.center_point_id
            base["radius"] = self._expression_to_dict(entity.radius)
        elif isinstance(entity, SketchArc):
            base["center_point_id"] = entity.center_point_id
            base["start_point_id"] = entity.start_point_id
            base["end_point_id"] = entity.end_point_id
        elif isinstance(entity, SketchInfiniteLine):
            base["point_a_id"] = entity.point_a_id
            base["point_b_id"] = entity.point_b_id
        elif isinstance(entity, SketchSpline):
            base["control_point_ids"] = entity.control_point_ids
        return base

    def _sketch_entity_from_dict(
        self,
        data: dict,
    ) -> SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline:
        entity_type = SketchEntityType(data["type"])
        common = {
            "id": data["id"],
            "name": data["name"],
            "type": entity_type,
            "visible": data.get("visible", True),
            "construction": data.get("construction", False),
            "selectable": data.get("selectable", True),
            "style": self._style_from_dict(data.get("style")),
            "metadata": Metadata(data.get("metadata", {})),
        }
        if entity_type is SketchEntityType.POINT:
            return SketchPoint(
                x=self._expression_from_dict(data["x"]),
                y=self._expression_from_dict(data["y"]),
                **common,
            )
        if entity_type is SketchEntityType.LINE_SEGMENT:
            return SketchLineSegment(
                start_point_id=data["start_point_id"],
                end_point_id=data["end_point_id"],
                **common,
            )
        if entity_type is SketchEntityType.CIRCLE:
            return SketchCircle(
                center_point_id=data["center_point_id"],
                radius=self._expression_from_dict(data["radius"]),
                **common,
            )
        if entity_type is SketchEntityType.ARC:
            if "point_a_id" in data:
                return SketchArc(
                    center_point_id=data["point_a_id"],
                    start_point_id=data["point_b_id"],
                    end_point_id=data["point_c_id"],
                    **common,
                )
            return SketchArc(
                center_point_id=data["center_point_id"],
                start_point_id=data["start_point_id"],
                end_point_id=data["end_point_id"],
                **common,
            )
        if entity_type is SketchEntityType.SPLINE:
            return SketchSpline(
                control_point_ids=data.get("control_point_ids", []),
                **common,
            )
        return SketchInfiniteLine(
            point_a_id=data["point_a_id"],
            point_b_id=data["point_b_id"],
            **common,
        )

    # ------------------------------------------------------------------
    # Block diagram serialization
    # ------------------------------------------------------------------

    def _block_instance_to_dict(self, inst: BlockInstance) -> dict:
        return {
            "id": inst.instance_id,
            "block_type": inst.block_type,
            "parameters": inst.parameters,
            "input_ports": [
                {"name": p.name, "shape": p.shape} for p in inst.input_ports
            ],
            "output_ports": [
                {"name": p.name, "shape": p.shape} for p in inst.output_ports
            ],
            "position": inst.position,
        }

    def _block_instance_from_dict(self, data: dict) -> BlockInstance:
        return BlockInstance(
            instance_id=data["id"],
            block_type=data["block_type"],
            parameters=data.get("parameters", {}),
            input_ports=[
                PortSpec(p["name"], tuple(p["shape"])) for p in data.get("input_ports", [])
            ],
            output_ports=[
                PortSpec(p["name"], tuple(p["shape"])) for p in data.get("output_ports", [])
            ],
            position=tuple(data.get("position", [0.0, 0.0])),
        )

    def _block_connection_to_dict(self, conn: Connection) -> dict:
        return {
            "src_instance": conn.src_instance,
            "src_port": conn.src_port,
            "dst_instance": conn.dst_instance,
            "dst_port": conn.dst_port,
        }

    def _block_connection_from_dict(self, data: dict) -> Connection:
        return Connection(
            src_instance=data["src_instance"],
            src_port=data["src_port"],
            dst_instance=data["dst_instance"],
            dst_port=data["dst_port"],
        )

    def _block_diagram_to_dict(self, diagram: BlockDiagram) -> dict:
        return {
            "instances": {
                inst.instance_id: self._block_instance_to_dict(inst)
                for inst in diagram.instances.values()
            },
            "connections": [
                self._block_connection_to_dict(c)
                for c in diagram.connections
            ],
        }

    def _block_diagram_from_dict(self, data: dict | None) -> BlockDiagram | None:
        if data is None:
            return None
        instances = {}
        for instance_id, item in data.get("instances", {}).items():
            item_with_id = dict(item)
            item_with_id.setdefault("id", instance_id)
            inst = self._block_instance_from_dict(item_with_id)
            instances[instance_id] = inst
        connections = [
            self._block_connection_from_dict(c)
            for c in data.get("connections", [])
        ]
        return BlockDiagram(instances=instances, connections=connections)
