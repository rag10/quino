"""Entity-level commands extracted from ApplicationService.

Owns the entity index, generic rename/delete/update-property dispatchers,
gravity CRUD, and the validation/scalar/style helpers used by the dispatcher.

The dispatcher needs to route to entity-type-specific operations that live in
the other command-services, so this class receives references to BodyCommands,
JointCommands, SketchCommands, ForceCommands, ParameterCommands, and
PoseCommands. EntityCommands must be instantiated AFTER all the others.
"""
from __future__ import annotations

import re

from quino.application._context import ServiceContext
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput
from quino.domain.model import (
    Body,
    Driver,
    GravityLoad,
    Joint,
    Load,
    Marker,
    Parameter,
    Project,
    ScalarProperty,
    Sensor,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    Slider,
    Spring,
)
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import ScalarValue as _WsScalarValue


class EntityCommands:
    _PLAIN_NUMBER_RE = re.compile(r"^\s*[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)\s*$")

    _STYLE_FIELD_TYPES: dict[str, type] = {
        "color": str,
        "visible": bool,
        "line_width": float,
        "marker_size": float,
    }

    def __init__(
        self,
        ctx: ServiceContext,
        *,
        bodies,
        joints,
        sketch,
        forces,
        parameters,
        poses,
    ) -> None:
        self._ctx = ctx
        self._bodies = bodies
        self._joints = joints
        self._sketch = sketch
        self._forces = forces
        self._parameters = parameters
        self._poses = poses
        self._entity_index: dict[str, object] | None = None

    @property
    def _project(self) -> Project:
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No project loaded")
        return project

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _mm_expression(self, value: float) -> str:
        return f"{value:.6g} mm"

    def _normalize_angle_expression(self, expression: str) -> str:
        stripped = expression.strip()
        if self._PLAIN_NUMBER_RE.fullmatch(stripped):
            return f"{stripped} deg"
        return expression

    def _is_literal_expression(self, expression: str) -> bool:
        """Return True if expression is a plain number with optional unit (no parameters)."""
        cleaned = expression.strip()
        for unit in ("mm", "m", "deg", "rad", "s"):
            if cleaned.endswith(unit):
                cleaned = cleaned[: -len(unit)].strip()
                break
        try:
            float(cleaned)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Entity index / find
    # ------------------------------------------------------------------

    def invalidate_index(self) -> None:
        self._entity_index = None

    def _resolve_case_chain(self, case):
        """Return cases from root to leaf for the given case."""
        from quino.services.workspace_composition import _resolve_case_chain
        return _resolve_case_chain(self._project, case)

    def _build_entity_index(self) -> dict[str, object]:
        project = self._project
        index: dict[str, object] = {}
        if project.sketch is not None:
            index[project.sketch.id] = project.sketch
            for entity in project.sketch.entities.values():
                index[entity.id] = entity
            for constraint in project.sketch.constraints.values():
                index[constraint.id] = constraint
        for collection in (
            project.model.bodies,
            project.model.joints,
            project.model.sliders,
            project.model.drivers,
            project.model.loads,
            project.model.sensors,
            project.model.springs,
            project.parameters,
        ):
            for entity in collection:
                index[entity.id] = entity
        for body in project.model.bodies:
            for marker in body.markers:
                index[marker.id] = marker

        # Apply structural deltas from the active case chain (root → leaf)
        case = self._ctx.get_active_case()
        if case is not None:
            from quino.serialization.json_io import JsonMapper
            mapper = JsonMapper()
            deserializers = {
                "bodies": mapper._body_from_dict,
                "joints": mapper._joint_from_dict,
                "sliders": mapper._slider_from_dict,
                "drivers": mapper._driver_from_dict,
                "loads": mapper._load_from_dict,
                "sensors": mapper._sensor_from_dict,
                "springs": mapper._spring_from_dict,
            }
            removed_ids: set[str] = set()
            all_overrides: dict[str, _WsScalarValue] = {}
            for inherited_case in self._resolve_case_chain(case):
                # Apply removals first
                removed_ids.update(inherited_case.removed_entity_ids)
                # Then apply additions
                for domain, entities_data in inherited_case.added_entities.items():
                    deserializer = deserializers.get(domain)
                    if deserializer is None:
                        continue
                    for entity_data in entities_data:
                        try:
                            entity = deserializer(entity_data)
                            index[entity.id] = entity
                            if domain == "bodies":
                                for marker in entity.markers:
                                    index[marker.id] = marker
                        except Exception:
                            pass
                # Collect invariant overrides
                all_overrides.update(inherited_case.invariant_values)
            # Remove entities that were deleted anywhere in the chain
            for entity_id in removed_ids:
                if entity_id in index:
                    del index[entity_id]
            # Apply invariant overrides to entities in the index
            for path, scalar in all_overrides.items():
                parts = path.split("/")
                if len(parts) >= 3:
                    entity_id = parts[1]
                    entity = index.get(entity_id)
                    if entity is not None:
                        prop = parts[2]
                        current = getattr(entity, prop, None)
                        if isinstance(current, ScalarProperty):
                            new_expr = f"{scalar.value:g} {scalar.unit}".strip() if scalar.unit else f"{scalar.value:g}"
                            setattr(
                                entity,
                                prop,
                                ScalarProperty(
                                    expression=new_expr,
                                    unit=scalar.unit or current.unit,
                                    expected_dimension=current.expected_dimension,
                                ),
                            )
                        elif current is None:
                            # Property is unset; infer dimension and create ScalarProperty
                            from quino.domain.types import Dimension, DriverType
                            dim_map: dict[str, Dimension] = {
                                "mass": Dimension.MASS,
                                "x": Dimension.LENGTH,
                                "y": Dimension.LENGTH,
                                "origin_x": Dimension.LENGTH,
                                "origin_y": Dimension.LENGTH,
                                "travel_min": Dimension.LENGTH,
                                "travel_max": Dimension.LENGTH,
                                "angle": Dimension.ANGLE,
                                "angle_limit_positive": Dimension.ANGLE,
                                "angle_limit_negative": Dimension.ANGLE,
                                "fx": Dimension.FORCE,
                                "fy": Dimension.FORCE,
                                "law": Dimension.ANGLE,
                            }
                            expected = dim_map.get(prop)
                            if prop == "law":
                                if isinstance(entity, Driver):
                                    expected = Dimension.ANGLE if entity.type is DriverType.ROTATION else Dimension.LENGTH
                                else:
                                    expected = Dimension.FORCE
                            if expected is not None:
                                default_unit = {
                                    Dimension.LENGTH: "mm",
                                    Dimension.ANGLE: "deg",
                                    Dimension.MASS: "kg",
                                    Dimension.FORCE: "N",
                                    Dimension.TORQUE: "N*mm",
                                    Dimension.TIME: "s",
                                }.get(expected, "")
                                new_expr = f"{scalar.value:g} {scalar.unit}".strip() if scalar.unit else f"{scalar.value:g}"
                                setattr(
                                    entity,
                                    prop,
                                    ScalarProperty(
                                        expression=new_expr,
                                        unit=scalar.unit or default_unit,
                                        expected_dimension=expected,
                                    ),
                                )
        return index

    def _find_entity(self, entity_id: str) -> object:
        if entity_id == "__gravity__":
            gravity = self._project.model.gravity
            if gravity is None:
                raise ValueError("No gravity in this project")
            return gravity
        if self._entity_index is None:
            self._entity_index = self._build_entity_index()
        entity = self._entity_index.get(entity_id)
        if entity is not None:
            return entity
        raise ValueError(f"Unknown entity: {entity_id}")

    def get_entity(self, entity_id: str) -> object | None:
        """Return any entity by id, or None if not found."""
        if entity_id == "__gravity__":
            project = self._ctx.project_provider()
            return project.model.gravity if project else None
        if entity_id.startswith("__reaction__"):
            joint_id = entity_id[len("__reaction__"):]
            project = self._ctx.project_provider()
            return project.reaction_outputs.get(joint_id) if project else None
        try:
            return self._find_entity(entity_id)
        except ValueError:
            return None

    def _find_case_entity_dict(self, entity_id: str) -> tuple[str, dict, Case] | None:
        """Search the active case chain's added_entities for *entity_id*.
        Returns (domain, entity_dict, owning_case) or None."""
        case = self._ctx.get_active_case()
        if case is None:
            return None
        for inherited_case in reversed(self._resolve_case_chain(case)):
            for domain, entities in inherited_case.added_entities.items():
                for ent in entities:
                    if ent.get("id") == entity_id:
                        return (domain, ent, inherited_case)
        return None

    def _entity_exists_in_base(self, entity_id: str) -> bool:
        """Return True if the entity exists in the base project model."""
        project = self._project
        if any(b.id == entity_id for b in project.model.bodies):
            return True
        if any(s.id == entity_id for s in project.model.sliders):
            return True
        if any(j.id == entity_id for j in project.model.joints):
            return True
        if any(d.id == entity_id for d in project.model.drivers):
            return True
        if any(l.id == entity_id for l in project.model.loads):
            return True
        if any(s.id == entity_id for s in project.model.sensors):
            return True
        if any(sp.id == entity_id for sp in project.model.springs):
            return True
        for body in project.model.bodies:
            if any(m.id == entity_id for m in body.markers):
                return True
        return False

    def _remove_from_case_added_entities(self, entity_id: str) -> bool:
        """Remove *entity_id* from the active case's added_entities.
        Return True if found and removed."""
        case = self._ctx.get_active_case()
        if case is None:
            return False
        for domain, entities in list(case.added_entities.items()):
            for i, ent in enumerate(entities):
                if ent.get("id") == entity_id:
                    entities.pop(i)
                    if not entities:
                        case.added_entities.pop(domain, None)
                    return True
        return False

    def _record_case_removal(self, entity_id: str) -> None:
        """Record *entity_id* as removed in the active case."""
        case = self._ctx.get_active_case()
        if case is None:
            return
        if entity_id not in case.removed_entity_ids:
            case.removed_entity_ids.append(entity_id)

    def _entity_is_removed_in_chain(self, entity_id: str) -> bool:
        """Return True if the entity is removed by any case in the active chain."""
        case = self._ctx.get_active_case()
        if case is None:
            return False
        for inherited_case in self._resolve_case_chain(case):
            if entity_id in inherited_case.removed_entity_ids:
                return True
        return False

    # ------------------------------------------------------------------
    # Scalar property build/assign
    # ------------------------------------------------------------------

    def _build_validated_scalar_property(
        self, entity: object, property_path: str, expression: str
    ) -> ScalarProperty:
        dimension_map = {
            "x": Dimension.LENGTH,
            "y": Dimension.LENGTH,
            "origin_x": Dimension.LENGTH,
            "origin_y": Dimension.LENGTH,
            "travel_min": Dimension.LENGTH,
            "travel_max": Dimension.LENGTH,
            "angle_limit_positive": Dimension.ANGLE,
            "angle_limit_negative": Dimension.ANGLE,
            "angle": Dimension.ANGLE,
            "mass": Dimension.MASS,
            "fx": Dimension.FORCE,
            "fy": Dimension.FORCE,
            "law": getattr(entity, "law", None).expected_dimension if isinstance(entity, Driver) else None,
        }
        if property_path not in dimension_map:
            raise ValueError(f"Unsupported property path: {property_path}")
        current = getattr(entity, property_path, None)
        unit = (
            "deg" if property_path == "angle"
            else "kg" if property_path == "mass"
            else "N" if property_path in ("fx", "fy")
            else "mm"
        )
        if current is not None and isinstance(current, ScalarProperty):
            unit = current.unit
        scalar = ScalarProperty(
            expression=expression, unit=unit, expected_dimension=dimension_map[property_path]
        )
        if property_path == "law":
            variables = {"t": self._ctx.units.quantity(0.0, "s")}
        elif property_path in {"fx", "fy"}:
            variables = self._ctx.load_expression_variables(self._project, time_value=0.0)
        else:
            variables = None
        self._ctx.expressions.evaluate_property(
            scalar, self._project.parameters, variables=variables
        )
        return scalar

    def _assign_scalar_property(
        self, entity: object, property_path: str, scalar: ScalarProperty
    ) -> None:
        setattr(entity, property_path, scalar)
        if isinstance(entity, Body) and property_path == "mass":
            value = self._ctx.expressions.evaluate_property(
                scalar, self._project.parameters
            ).value
            entity.com_marker().visible = value != 0

    # ------------------------------------------------------------------
    # Case overlay helpers
    # ------------------------------------------------------------------

    def _entity_overlay_path(self, entity: object, property_path: str) -> str:
        if isinstance(entity, Body):
            return f"bodies/{entity.id}/{property_path}"
        if isinstance(entity, Driver):
            return f"drivers/{entity.id}/{property_path}"
        if isinstance(entity, Spring):
            return f"springs/{entity.id}/{property_path}"
        if isinstance(entity, Load):
            return f"loads/{entity.id}/{property_path}"
        raise TypeError(f"Entity type {type(entity).__name__} does not support overlay")

    # ------------------------------------------------------------------
    # Style update
    # ------------------------------------------------------------------

    def _apply_style_update(
        self, entity: object, property_path: str, value: PropertyValueInput
    ) -> None:
        field = property_path.split(".", 1)[1]
        expected_type = self._STYLE_FIELD_TYPES.get(field)
        if expected_type is None:
            raise ValueError(f"Unknown style field: {field}")
        if expected_type is bool and value.kind != "boolean":
            raise ValueError(f"Style field '{field}' requires a boolean value")
        if expected_type is str and value.kind != "expression":
            raise ValueError(f"Style field '{field}' requires a string/expression value")
        if expected_type is float and value.kind != "expression":
            raise ValueError(f"Style field '{field}' requires a numeric expression")
        if expected_type is float:
            try:
                float_value = float(value.value)
            except Exception:
                raise ValueError(f"Style field '{field}' requires a numeric value")
            self._ctx.snapshot()
            setattr(entity.style, field, float_value)
            return
        self._ctx.snapshot()
        setattr(entity.style, field, value.value)

    # ------------------------------------------------------------------
    # Name validation / rename
    # ------------------------------------------------------------------

    def _validate_entity_name(self, entity: object, new_name: str) -> None:
        project = self._project
        if isinstance(entity, Sketch):
            return
        if isinstance(entity, (SketchPoint, SketchLineSegment, SketchCircle, SketchArc, SketchInfiniteLine)):
            self._sketch._validate_sketch_entity_name(new_name, entity.id)
        elif isinstance(entity, SketchConstraint):
            self._sketch._validate_sketch_constraint_name(new_name, entity.id)
        elif isinstance(entity, Body):
            self._ctx.validation.ensure_unique_name(project.model.bodies, new_name, entity.id)
        elif isinstance(entity, Joint):
            self._ctx.validation.ensure_unique_name(project.model.joints, new_name, entity.id)
        elif isinstance(entity, Slider):
            self._ctx.validation.ensure_unique_name(project.model.sliders, new_name, entity.id)
        elif isinstance(entity, Driver):
            self._ctx.validation.ensure_unique_name(project.model.drivers, new_name, entity.id)
        elif isinstance(entity, Sensor):
            self._ctx.validation.ensure_unique_name(project.model.sensors, new_name, entity.id)
        elif isinstance(entity, Parameter):
            self._ctx.validation.ensure_unique_name(project.parameters, new_name, entity.id)
        elif isinstance(entity, Marker):
            body = self._bodies._find_body_by_marker(entity.id)
            self._ctx.validation.ensure_unique_marker_name(body, new_name, entity.id)

    def _rename_entity_no_snapshot(self, entity: object, new_name: str) -> None:
        entity.name = new_name

    def rename_entity(self, entity_id: str, new_name: str) -> None:
        entity = self._find_entity(entity_id)
        self._validate_entity_name(entity, new_name)
        self._ctx.snapshot()
        case = self._ctx.get_active_case()
        if case is not None and self._entity_exists_in_base(entity_id):
            # Record the rename in the case instead of mutating baseline
            case.reference_overrides.setdefault(entity_id, {})["name"] = new_name
            return
        if case is not None:
            # Entity may be in added_entities — update the dict
            case_ent = self._find_case_entity_dict(entity_id)
            if case_ent is not None:
                domain, ent_dict, owning_case = case_ent
                ent_dict["name"] = new_name
                return
        self._rename_entity_no_snapshot(entity, new_name)

    # ------------------------------------------------------------------
    # Edge-order validation
    # ------------------------------------------------------------------

    def _validated_edge_order(self, body: Body, raw_value: str) -> list[str]:
        requested_names = [item.strip() for item in raw_value.split(",") if item.strip()]
        structural = body.structural_markers()
        structural_names = [marker.name for marker in structural]
        if sorted(requested_names) != sorted(structural_names):
            raise ValueError("edge_order must list every structural marker name exactly once")
        marker_by_name = {marker.name: marker.id for marker in structural}
        return [marker_by_name[name] for name in requested_names]

    # ------------------------------------------------------------------
    # Gravity
    # ------------------------------------------------------------------

    def add_gravity(self) -> None:
        project = self._project
        if project.model.gravity is not None:
            return
        self._ctx.snapshot()
        project.model.gravity = GravityLoad()

    def delete_gravity(self) -> None:
        project = self._project
        if project.model.gravity is None:
            return
        self._ctx.snapshot()
        project.model.gravity = None

    def _update_gravity_property(self, path: str, value: PropertyValueInput) -> None:
        gravity = self._project.model.gravity
        if gravity is None:
            raise ValueError("No gravity in this project")
        if path not in {"magnitude", "direction_x", "direction_y"}:
            raise ValueError(f"Unknown gravity property: {path}")
        if value.kind != "expression":
            raise ValueError(f"Gravity {path} requires a numeric expression")
        try:
            float_val = float(value.value)
        except (ValueError, TypeError):
            raise ValueError(f"Gravity {path} must be a number, got: {value.value!r}")
        self._ctx.snapshot()
        setattr(gravity, path, float_val)

    # ------------------------------------------------------------------
    # update_property dispatcher
    # ------------------------------------------------------------------

    def update_property(
        self, entity_id: str, property_path: str, value: PropertyValueInput
    ) -> None:
        if entity_id == "__gravity__":
            self._update_gravity_property(property_path, value)
            return
        entity = self._find_entity(entity_id)
        if isinstance(entity, Marker) and entity.type is MarkerType.COM:
            body = self._bodies._find_body_by_marker(entity.id)
            if property_path in {"x", "y"}:
                if body.type is BodyType.POINT_MASS:
                    raise ValueError("CoM of a point mass cannot be moved independently")
                if body.type is BodyType.BAR:
                    raise ValueError("Bar CoM must be edited with position_percent or position_distance")
            if body.type is BodyType.BAR and property_path in {"position_percent", "position_distance"}:
                self._bodies._update_bar_com_property(body, property_path, value)
                return
        if isinstance(entity, Joint) and property_path in {"friction_coulomb", "friction_viscous", "friction_pin_radius"}:
            self._joints._update_joint_friction_property(entity, property_path, value)
            return
        if isinstance(entity, Joint) and property_path in {"angle_limit_positive", "angle_limit_negative"}:
            self._joints._update_joint_angular_limit_property(entity, property_path, value)
            return
        if isinstance(entity, Spring) and property_path in {"stiffness", "damping", "rest_value", "law"}:
            self._forces.update_spring_property(entity.id, property_path, value)
            return
        if isinstance(entity, Marker) and property_path in {"x", "y"}:
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Marker coordinates require an expression value")
            target_x = value.value if property_path == "x" else entity.x.expression
            target_y = value.value if property_path == "y" else entity.y.expression
            self._bodies.move_marker(entity.id, target_x, target_y)
            return
        if isinstance(entity, Slider) and property_path in {"origin_x", "origin_y"}:
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Slider origin coordinates require an expression value")
            target_x = value.value if property_path == "origin_x" else entity.origin_x.expression
            target_y = value.value if property_path == "origin_y" else entity.origin_y.expression
            self._joints._move_slider_origin(entity.id, target_x, target_y)
            return
        if isinstance(entity, Slider) and property_path == "angle":
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Slider angle requires an expression value")
            self._joints._rotate_slider(entity.id, value.value)
            return
        if property_path == "name":
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Name updates require an expression/string value")
            self._validate_entity_name(entity, value.value)
            self._ctx.snapshot()
            self._rename_entity_no_snapshot(entity, value.value)
            return
        if property_path == "edge_order":
            if not isinstance(entity, Body):
                raise ValueError("edge_order only applies to Body")
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("edge_order updates require a comma-separated expression/string value")
            edge_order = self._validated_edge_order(entity, value.value)
            self._ctx.snapshot()
            entity.edge_order = edge_order
            return
        if property_path in {"visible", "closed_shape"}:
            if value.kind != "boolean" or not isinstance(value.value, bool):
                raise ValueError("Boolean property requires a boolean input")
            self._ctx.snapshot()
            setattr(entity, property_path, value.value)
            return
        if property_path in {"mass", "travel_min", "travel_max"} and value.kind == "null":
            self._ctx.snapshot()
            setattr(entity, property_path, None)
            return
        if property_path.startswith("style."):
            self._apply_style_update(entity, property_path, value)
            return
        if property_path == "law":
            if not isinstance(entity, Driver):
                raise ValueError("law only applies to Driver")
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Driver law requires an expression value")
            law = ScalarProperty(
                expression=value.value,
                unit=entity.law.unit,
                expected_dimension=entity.law.expected_dimension,
            )
            evaluated = self._ctx.expressions.evaluate_property(
                law,
                self._project.parameters,
                variables={"t": self._ctx.units.quantity(0.0, "s")},
            )
            _case = self._ctx.get_active_case()
            if _case is not None:
                _path = f"drivers/{entity.id}/law"
                float_val = float(evaluated.value)
                self._ctx.snapshot()
                _case.invariant_values[_path] = _WsScalarValue(value=float_val, unit=law.unit)
                return
            self._ctx.snapshot()
            entity.law = law
            return
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError("Scalar properties require an expression value")
        scalar = self._build_validated_scalar_property(entity, property_path, value.value)
        # If a case is active and the entity is a case-overridable type, route to
        # the case overlay instead of mutating the base model.
        case = self._ctx.get_active_case()
        if case is not None and isinstance(entity, (Body, Driver, Spring, Load)):
            float_val = float(
                self._ctx.expressions.evaluate_property(
                    scalar, self._project.parameters
                ).value
            )
            path = self._entity_overlay_path(entity, property_path)
            self._ctx.snapshot()
            case.invariant_values[path] = _WsScalarValue(value=float_val, unit=scalar.unit)
            return
        self._ctx.snapshot()
        self._assign_scalar_property(entity, property_path, scalar)

    # ------------------------------------------------------------------
    # delete_entity dispatcher
    # ------------------------------------------------------------------

    def delete_entity(self, entity_id: str) -> None:
        if entity_id == "__gravity__":
            self.delete_gravity()
            return
        project = self._project
        if project.sketch is not None and entity_id in project.sketch.entities:
            self._sketch.delete_sketch_entity(entity_id)
            return
        if project.sketch is not None and entity_id in project.sketch.constraints:
            self._sketch.delete_sketch_constraint(entity_id)
            return

        case = self._ctx.get_active_case()

        # 1. Try to remove from the active case's added_entities first.
        if self._remove_from_case_added_entities(entity_id):
            self._ctx.invalidate_pose_state()
            return

        # 2. Check if the entity was added by a parent case — if so, record
        #    removal in the active case (the child).
        case_entity = self._find_case_entity_dict(entity_id)
        if case_entity is not None:
            self._ctx.snapshot()
            self._record_case_removal(entity_id)
            self._ctx.invalidate_pose_state()
            return

        # 3. Determine entity type so we can apply cascade deletion when
        #    there is no active case (direct baseline edit).
        entity_type = None
        if any(b.id == entity_id for b in project.model.bodies):
            entity_type = "body"
        elif any(s.id == entity_id for s in project.model.sliders):
            entity_type = "slider"
        elif any(j.id == entity_id for j in project.model.joints):
            entity_type = "joint"
        elif any(d.id == entity_id for d in project.model.drivers):
            entity_type = "driver"
        elif any(l.id == entity_id for l in project.model.loads):
            entity_type = "load"
        elif any(s.id == entity_id for s in project.model.sensors):
            entity_type = "sensor"
        elif any(sp.id == entity_id for sp in project.model.springs):
            entity_type = "spring"
        else:
            # Marker deletion
            body = self._bodies._find_body_by_marker(entity_id)
            if any(marker.id == entity_id and marker.type is MarkerType.COM for marker in body.markers):
                raise ValueError("CoM marker cannot be deleted")
            if len(body.structural_markers()) <= 1:
                raise ValueError("The last structural marker of a body cannot be deleted")
            self._ctx.snapshot()
            removed_joint_ids = {
                joint.id
                for joint in project.model.joints
                if joint.endpoint_a.marker_id == entity_id or joint.endpoint_b.marker_id == entity_id
            }
            if case is None:
                body.markers = [marker for marker in body.markers if marker.id != entity_id]
                body.edge_order = [marker_id for marker_id in body.edge_order if marker_id != entity_id]
                project.model.joints = [
                    joint
                    for joint in project.model.joints
                    if joint.endpoint_a.marker_id != entity_id and joint.endpoint_b.marker_id != entity_id
                ]
                project.model.drivers = [
                    driver for driver in project.model.drivers if driver.target_joint_id not in removed_joint_ids
                ]
                project.model.sensors = [
                    sensor
                    for sensor in project.model.sensors
                    if entity_id not in sensor.marker_ids
                ]
                project.model.loads = [
                    load for load in project.model.loads if load.target_marker_id != entity_id
                ]
                if len(body.structural_markers()) == 1:
                    body.type = BodyType.POINT_MASS
                    body.closed_shape = False
                elif body.type is BodyType.BODY and len(body.structural_markers()) == 2:
                    body.closed_shape = True
                self._bodies._sync_special_com_marker(body)
            else:
                self._record_case_removal(entity_id)
            self._ctx.invalidate_pose_state()
            return

        # 3. Handle structural entity deletion.
        self._ctx.snapshot()

        if entity_type == "body":
            body = self._bodies._find_body(entity_id)
            marker_ids = {marker.id for marker in body.markers}
            removed_joint_ids = {
                joint.id
                for joint in project.model.joints
                if joint.endpoint_a.marker_id in marker_ids or joint.endpoint_b.marker_id in marker_ids
            }
            if case is None:
                project.model.joints = [
                    joint
                    for joint in project.model.joints
                    if joint.endpoint_a.marker_id not in marker_ids and joint.endpoint_b.marker_id not in marker_ids
                ]
                project.model.drivers = [
                    driver for driver in project.model.drivers if driver.target_joint_id not in removed_joint_ids
                ]
                project.model.loads = [
                    load for load in project.model.loads if load.target_marker_id not in marker_ids
                ]
                project.model.bodies = [item for item in project.model.bodies if item.id != entity_id]
            self._record_case_removal(entity_id)
            self._ctx.invalidate_pose_state()
            return

        if entity_type == "slider":
            slider_joint_ids = {
                joint.id
                for joint in project.model.joints
                if joint.endpoint_a.slider_id == entity_id or joint.endpoint_b.slider_id == entity_id
            }
            if case is None:
                project.model.joints = [
                    joint
                    for joint in project.model.joints
                    if joint.endpoint_a.slider_id != entity_id and joint.endpoint_b.slider_id != entity_id
                ]
                project.model.drivers = [
                    driver for driver in project.model.drivers if driver.target_joint_id not in slider_joint_ids
                ]
                project.model.sliders = [item for item in project.model.sliders if item.id != entity_id]
            self._record_case_removal(entity_id)
            self._ctx.invalidate_pose_state()
            return

        if entity_type == "joint":
            if case is None:
                project.model.joints = [item for item in project.model.joints if item.id != entity_id]
                project.model.drivers = [driver for driver in project.model.drivers if driver.target_joint_id != entity_id]
            self._record_case_removal(entity_id)
            self._ctx.invalidate_pose_state()
            return

        if entity_type == "driver":
            if case is None:
                project.model.drivers = [item for item in project.model.drivers if item.id != entity_id]
                self._cleanup_driver_velocities({entity_id})
            self._record_case_removal(entity_id)
            return

        if entity_type == "load":
            if case is None:
                project.model.loads = [item for item in project.model.loads if item.id != entity_id]
            self._record_case_removal(entity_id)
            return

        if entity_type == "sensor":
            if case is None:
                project.model.sensors = [item for item in project.model.sensors if item.id != entity_id]
            self._record_case_removal(entity_id)
            return

        if entity_type == "spring":
            if case is None:
                project.model.springs = [item for item in project.model.springs if item.id != entity_id]
            self._record_case_removal(entity_id)
            return

    def _cleanup_driver_velocities(self, removed_driver_ids: set[str]) -> None:
        project = self._ctx.project_provider()
        if not removed_driver_ids or project is None:
            return
        for pose in project.poses:
            for driver_id in list(pose.initial_velocities.keys()):
                if driver_id in removed_driver_ids:
                    pose.initial_velocities.pop(driver_id, None)
