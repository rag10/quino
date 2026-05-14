from __future__ import annotations

import math
from typing import Any

from quino.domain.model import Project
from quino.domain.types import Dimension, JointEndpointKind, JointType
from quino.services.expressions import ExpressionService
from quino.simulation.assembler import AssembledBody, AssembledLoad, AssembledMechanism, AssembledSlider, AssembledSpring


def _body_com_global(body: AssembledBody) -> tuple[float, float]:
    cos_a = math.cos(body.angle)
    sin_a = math.sin(body.angle)
    return (
        body.origin_x + cos_a * body.com_local_x - sin_a * body.com_local_y,
        body.origin_y + sin_a * body.com_local_x + cos_a * body.com_local_y,
    )


def _com_rel(body: AssembledBody, marker) -> tuple[float, float]:
    return (marker.local_x - body.com_local_x, marker.local_y - body.com_local_y)


def _safe_var(name: str) -> str:
    """Sanitize a string so it can be used as a Python variable name."""
    safe = name.replace("-", "_").replace(" ", "_").replace(".", "_")
    # avoid leading digits
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe


def _py_repr(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_py_repr(v) for v in value) + "]"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    if value is None:
        return "None"
    return repr(value)


def _generate_interp_helper() -> list[str]:
    return [
        "def _interp(t, times, values):",
        "    if t <= times[0]:",
        "        return float(values[0])",
        "    if t >= times[-1]:",
        "        return float(values[-1])",
        "    for i in range(len(times) - 1):",
        "        if times[i] <= t <= times[i + 1]:",
        "            dt = times[i + 1] - times[i]",
        "            if dt == 0:",
        "                return float(values[i])",
        "            return float(values[i] + (values[i + 1] - values[i]) * (t - times[i]) / dt)",
        "    return float(values[-1])",
        "",
    ]


def _generate_driver_data(
    project: Project,
    assembled: AssembledMechanism,
    duration: float,
    steps: int,
    expression_service: ExpressionService,
) -> list[str]:
    lines: list[str] = ["# --- Driver data ---", ""]
    dt = duration / max(steps, 1)
    times = [i * dt for i in range(steps + 1)]

    for driver in assembled.drivers:
        values: list[float] = []
        for t in times:
            quantity = expression_service.evaluate_expression(
                driver.law_expression,
                project.parameters,
                variables={"t": expression_service.unit_service.quantity(t, "s")},
            )
            if driver.expected_dimension == Dimension.ANGLE.value:
                output_unit = "rad"
            elif driver.expected_dimension == Dimension.LENGTH.value:
                output_unit = "m"
            else:
                output_unit = driver.unit
            value = expression_service.unit_service.convert(quantity, output_unit)
            values.append(value)

        derivatives: list[float] = []
        for i in range(len(times)):
            if len(values) == 1:
                derivatives.append(0.0)
            elif i == 0:
                derivatives.append((values[1] - values[0]) / dt)
            elif i == len(values) - 1:
                derivatives.append((values[-1] - values[-2]) / dt)
            else:
                derivatives.append((values[i + 1] - values[i - 1]) / (2 * dt))

        safe_id = driver.driver_id.replace("-", "_")
        lines.append(f"_driver_{safe_id}_times = {_py_repr(times)}")
        lines.append(f"_driver_{safe_id}_values = {_py_repr(values)}")
        lines.append(f"_driver_{safe_id}_derivatives = {_py_repr(derivatives)}")
        lines.append("")
        lines.append(f"def _driver_{safe_id}_offset(mbs, t, itemNumber, lOffset):")
        lines.append(f"    return _interp(t, _driver_{safe_id}_times, _driver_{safe_id}_values)")
        lines.append("")
        lines.append(f"def _driver_{safe_id}_offset_t(mbs, t, itemNumber, lOffset):")
        lines.append(f"    return _interp(t, _driver_{safe_id}_times, _driver_{safe_id}_derivatives)")
        lines.append("")

    return lines


def _generate_bodies(project: Project, assembled: AssembledMechanism) -> list[str]:
    lines: list[str] = ["# --- Bodies ---", ""]
    domain_body_map = {body.id: body for body in project.model.bodies}
    for body in assembled.bodies.values():
        b = _safe_var(body.body_id)
        domain_body = domain_body_map.get(body.body_id)
        if domain_body and domain_body.edge_order:
            points: list[list[float]] = []
            for marker_id in domain_body.edge_order:
                marker = body.markers.get(marker_id)
                if marker is not None:
                    lx, ly = _com_rel(body, marker)
                    points.append([lx * 1e-3, ly * 1e-3, 0.0])
            if domain_body.closed_shape and points:
                points.append(points[0])
            if points:
                points_str = "[" + ", ".join(f"[{p[0]}, {p[1]}, 0.0]" for p in points) + "]"
                lines.append(f"graphics_{b} = [gr.Lines({points_str}, color=gr.color.steelblue)]")
            else:
                lines.append(f"graphics_{b} = []")
        else:
            lines.append(f"graphics_{b} = []")
        com_x, com_y = _body_com_global(body)
        lines.append(
            f"node_{b} = mbs.AddNode(item_interface.NodeRigidBody2D("
            f"referenceCoordinates=[{com_x * 1e-3}, {com_y * 1e-3}, {body.angle}]))"
        )
        lines.append(
            f"body_{b} = mbs.AddObject(item_interface.ObjectRigidBody2D("
            f"nodeNumber=node_{b}, physicsMass={body.mass}, physicsInertia={body.inertia * 1e-6}, "
            f"physicsCenterOfMass=[0.0, 0.0], "
            f"visualization=item_interface.VObjectRigidBody2D(graphicsData=graphics_{b})))"
        )
        if body.mass > 0 and assembled.gravity is not None:
            g = assembled.gravity
            lines.append(
                f"gm_{b} = mbs.AddMarker(item_interface.MarkerBodyMass("
                f"bodyNumber=body_{b}))"
            )
            lines.append(
                f"mbs.AddLoad(item_interface.LoadMassProportional("
                f"markerNumber=gm_{b}, loadVector=[{g.magnitude * g.direction_x}, {g.magnitude * g.direction_y}, 0.0]))"
            )
    lines.append("")
    return lines


def _generate_joints(assembled: AssembledMechanism) -> list[str]:
    lines: list[str] = ["# --- Joints ---", ""]
    for joint in assembled.joints:
        a = joint.endpoint_a
        b = joint.endpoint_b
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.MARKER:
            lines.extend(_marker_to_marker_joint(assembled, joint, a, b, joint.type))
        elif a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.GROUND:
            lines.extend(_marker_to_ground_joint(assembled, joint, a, joint.type))
        elif b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.GROUND:
            lines.extend(_marker_to_ground_joint(assembled, joint, b, joint.type))
        elif a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.SLIDER:
            lines.extend(_marker_to_slider_joint(assembled, joint, a, b, joint.type, joint.name))
        elif b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.SLIDER:
            lines.extend(_marker_to_slider_joint(assembled, joint, b, a, joint.type, joint.name))
        else:
            lines.append(f"# Unsupported joint topology: {joint.name}")
    lines.append("")
    return lines


def _marker_to_marker_joint(assembled: AssembledMechanism, joint, endpoint_a, endpoint_b, joint_type) -> list[str]:
    lines: list[str] = []
    body_a = assembled.bodies[endpoint_a.body_id]
    body_b = assembled.bodies[endpoint_b.body_id]
    marker_a = body_a.markers[endpoint_a.marker_id]
    marker_b = body_b.markers[endpoint_b.marker_id]
    ma = _safe_var(f"m_{endpoint_a.body_id}_{endpoint_a.marker_id}")
    mb = _safe_var(f"m_{endpoint_b.body_id}_{endpoint_b.marker_id}")
    ba = _safe_var(body_a.body_id)
    bb = _safe_var(body_b.body_id)
    sj = _safe_var(joint.id)
    lx_a, ly_a = _com_rel(body_a, marker_a)
    lx_b, ly_b = _com_rel(body_b, marker_b)
    lines.append(
        f"{ma} = mbs.AddMarker(item_interface.MarkerBodyRigid(bodyNumber=body_{ba}, "
        f"localPosition=[{lx_a * 1e-3}, {ly_a * 1e-3}, 0.0]))"
    )
    lines.append(
        f"{mb} = mbs.AddMarker(item_interface.MarkerBodyRigid(bodyNumber=body_{bb}, "
        f"localPosition=[{lx_b * 1e-3}, {ly_b * 1e-3}, 0.0]))"
    )
    lines.append(
        f"pjoint_{sj} = mbs.AddObject(item_interface.ObjectJointRevolute2D("
        f"markerNumbers=[{ma}, {mb}]))"
    )
    if joint_type is JointType.RIGID:
        lines.append(
            f"mbs.CreateCoordinateConstraint(bodyNumbers=[body_{ba}, body_{bb}], "
            f"coordinates=[2, 2], offset=0.0)"
        )
    lines.extend(_joint_friction_lines(assembled, joint))
    return lines


def _marker_to_ground_joint(assembled: AssembledMechanism, joint, endpoint, joint_type) -> list[str]:
    lines: list[str] = []
    body = assembled.bodies[endpoint.body_id]
    marker = body.markers[endpoint.marker_id]
    b = _safe_var(body.body_id)
    sj = _safe_var(joint.id)
    gm = _safe_var(f"gm_{endpoint.body_id}_{endpoint.marker_id}")
    bm = _safe_var(f"bm_{endpoint.body_id}_{endpoint.marker_id}")
    lines.append(
        f"{gm} = mbs.AddMarker(item_interface.MarkerBodyRigid(bodyNumber=ground_object, "
        f"localPosition=[{marker.global_x * 1e-3}, {marker.global_y * 1e-3}, 0.0]))"
    )
    lx_bm, ly_bm = _com_rel(body, marker)
    lines.append(
        f"{bm} = mbs.AddMarker(item_interface.MarkerBodyRigid(bodyNumber=body_{b}, "
        f"localPosition=[{lx_bm * 1e-3}, {ly_bm * 1e-3}, 0.0]))"
    )
    lines.append(
        f"pjoint_{sj} = mbs.AddObject(item_interface.ObjectJointRevolute2D("
        f"markerNumbers=[{gm}, {bm}]))"
    )
    if joint_type is JointType.RIGID:
        lines.append(
            f"mbs.CreateCoordinateConstraint(bodyNumbers=[ground_object, body_{b}], "
            f"coordinates=[None, 2], offset=0.0)"
        )
    lines.extend(_joint_friction_lines(assembled, joint))
    return lines


def _marker_to_slider_joint(
    assembled: AssembledMechanism, joint, endpoint_a, endpoint_b, joint_type, joint_name
) -> list[str]:
    lines: list[str] = []
    body = assembled.bodies[endpoint_a.body_id]
    marker = body.markers[endpoint_a.marker_id]
    slider = assembled.sliders[endpoint_b.slider_id]
    b = _safe_var(body.body_id)
    j = _safe_var(joint_name)
    lx_nm, ly_nm = _com_rel(body, marker)
    lines.append(
        f"nm_{j} = mbs.AddMarker(item_interface.MarkerBodiesRelativeTranslationCoordinate("
        f"bodyNumbers=[ground_object, body_{b}], "
        f"localPosition0=[{slider.origin_x * 1e-3}, {slider.origin_y * 1e-3}, 0.0], "
        f"localPosition1=[{lx_nm * 1e-3}, {ly_nm * 1e-3}, 0.0], "
        f"axis0=[{slider.normal_x}, {slider.normal_y}, 0.0], offset=0.0))"
    )
    lines.append(
        f"gn_{j} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))"
    )
    lines.append(
        f"zm_{j} = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=gn_{j}, coordinate=0))"
    )
    sj = _safe_var(joint.id)
    lines.append(
        f"pjoint_{sj} = mbs.AddObject(item_interface.CoordinateConstraint("
        f"name={_py_repr(joint_name)}, markerNumbers=[nm_{j}, zm_{j}], offset=0.0))"
    )
    if joint_type is JointType.RIGID:
        lines.append(
            f"mbs.CreateCoordinateConstraint(bodyNumbers=[ground_object, body_{b}], "
            f"coordinates=[None, 2], offset=0.0)"
        )
    lines.extend(_slider_limit_stops(assembled, slider, body, marker, body.body_id, joint_name))
    lines.extend(_joint_friction_lines(assembled, joint))
    return lines


def _joint_friction_lines(assembled: AssembledMechanism, joint) -> list[str]:
    try:
        coulomb = float(joint.metadata.values.get("friction_coulomb", 0.0))
        viscous = float(joint.metadata.values.get("friction_viscous", 0.0))
    except (TypeError, ValueError):
        return []
    if abs(coulomb) <= 1e-12 and abs(viscous) <= 1e-12:
        return []
    sj = _safe_var(joint.id)
    lines: list[str] = []
    is_slider = joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER
    if is_slider:
        # Physics-based: F = μ × |F_normal| × sign(v) + c × v
        lines.append(f"def _joint_friction_{sj}(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):")
        lines.append("    try:")
        lines.append(f"        forces = mbs.GetObjectOutput(pjoint_{sj}, exudyn.OutputVariableType.Force)")
        lines.append("        raw = forces[0] if hasattr(forces, '__len__') else forces")
        lines.append("        N = abs(float(raw))")
        lines.append("    except Exception:")
        lines.append("        N = 0.0")
        lines.append("    sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0")
        lines.append(f"    return -({coulomb} * N * sign + {viscous} * float(velocity))")
        lines.append("")
        marker_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.MARKER else joint.endpoint_b
        slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
        body = assembled.bodies[marker_endpoint.body_id]
        marker = body.markers[marker_endpoint.marker_id]
        slider = assembled.sliders[slider_endpoint.slider_id]
        b = _safe_var(body.body_id)
        lx_fr, ly_fr = _com_rel(body, marker)
        lines.append(
            f"frtm_{sj} = mbs.AddMarker(item_interface.MarkerBodiesRelativeTranslationCoordinate("
            f"bodyNumbers=[ground_object, body_{b}], "
            f"localPosition0=[{slider.origin_x * 1e-3}, {slider.origin_y * 1e-3}, 0.0], "
            f"localPosition1=[{lx_fr * 1e-3}, {ly_fr * 1e-3}, 0.0], "
            f"axis0=[{slider.axis_x}, {slider.axis_y}, 0.0], offset=0.0))"
        )
        lines.append(f"frgn_{sj} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))")
        lines.append(f"frzm_{sj} = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=frgn_{sj}, coordinate=0))")
        marker_list = f"[frtm_{sj}, frzm_{sj}]"
    else:
        try:
            pin_radius_mm = float(joint.metadata.values.get("friction_pin_radius", 0.0))
        except (TypeError, ValueError):
            pin_radius_mm = 0.0
        if pin_radius_mm > 1e-12:
            r_m = pin_radius_mm * 1e-3
            lines.append(f"def _joint_friction_{sj}(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):")
            lines.append("    try:")
            lines.append(f"        forces = mbs.GetObjectOutput(pjoint_{sj}, exudyn.OutputVariableType.Force)")
            lines.append("        N = math.sqrt(float(forces[0])**2 + float(forces[1])**2)")
            lines.append("    except Exception:")
            lines.append("        N = 0.0")
            lines.append("    sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0")
            lines.append(f"    return -({coulomb} * N * {r_m} * sign + {viscous} * float(velocity))")
        else:
            lines.append(f"def _joint_friction_{sj}(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):")
            lines.append("    sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0")
            lines.append(f"    return -({viscous} * float(velocity) + {coulomb} * sign)")
        lines.append("")
        marker_lines, marker_names = _rotation_coordinate_markers(assembled, joint)
        lines.extend(marker_lines)
        marker_list = "[" + ", ".join(marker_names) + "]"
    lines.append(
        f"mbs.AddObject(item_interface.ObjectConnectorCoordinateSpringDamper("
        f"name={_py_repr(joint.name + '_friction')}, markerNumbers={marker_list}, "
        f"stiffness=0.0, damping=0.0, springForceUserFunction=_joint_friction_{sj}))"
    )
    return lines


def _slider_limit_stops(
    assembled: AssembledMechanism,
    slider: AssembledSlider,
    body: AssembledBody,
    marker,
    body_id: str,
    joint_name: str,
) -> list[str]:
    lines: list[str] = []
    if slider.travel_min is None and slider.travel_max is None:
        return lines
    b = _safe_var(body_id)
    j = _safe_var(joint_name)
    lx_rt, ly_rt = _com_rel(body, marker)
    lines.append(
        f"rtm_{j} = mbs.AddMarker(item_interface.MarkerBodiesRelativeTranslationCoordinate("
        f"bodyNumbers=[ground_object, body_{b}], "
        f"localPosition0=[{slider.origin_x * 1e-3}, {slider.origin_y * 1e-3}, 0.0], "
        f"localPosition1=[{lx_rt * 1e-3}, {ly_rt * 1e-3}, 0.0], "
        f"axis0=[{slider.axis_x}, {slider.axis_y}, 0.0], offset=0.0))"
    )
    lines.append(
        f"lgn_{j} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))"
    )
    lines.append(
        f"lzm_{j} = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=lgn_{j}, coordinate=0))"
    )
    lines.append(
        f"ldn_{j} = mbs.AddNode(item_interface.NodeGenericData("
        f"initialCoordinates=[0.0, 0.0, 0.0], numberOfDataCoordinates=3))"
    )
    lower = slider.travel_min * 1e-3 if slider.travel_min is not None else -1e30
    upper = slider.travel_max * 1e-3 if slider.travel_max is not None else 1e30
    lines.append(
        f"mbs.AddObject(item_interface.ObjectConnectorCoordinateSpringDamperExt("
        f"markerNumbers=[rtm_{j}, lzm_{j}], nodeNumber=ldn_{j}, "
        f"factor0=-1.0, factor1=1.0, stiffness=0.0, damping=0.0, useLimitStops=True, "
        f"limitStopsLower={lower}, limitStopsUpper={upper}, "
        f"limitStopsStiffness=1e6, limitStopsDamping=1e3))"
    )
    return lines


def _generate_drivers(assembled: AssembledMechanism) -> list[str]:
    lines: list[str] = ["# --- Drivers ---", ""]
    for driver in assembled.drivers:
        joint = next(joint for joint in assembled.joints if joint.id == driver.target_joint_id)
        safe_id = driver.driver_id.replace("-", "_")
        if driver.driver_type == "rotation":
            lines.extend(_rotation_driver(assembled, driver, joint, safe_id))
        elif driver.driver_type == "translation":
            lines.extend(_translation_driver(assembled, driver, joint, safe_id))
        else:
            lines.append(f"# Unsupported driver type: {driver.driver_type}")
    lines.append("")
    return lines


def _rotation_driver(assembled: AssembledMechanism, driver, joint, safe_id: str) -> list[str]:
    lines: list[str] = []
    marker_lines, marker_names = _rotation_coordinate_markers(assembled, joint)
    lines.extend(marker_lines)
    marker_list = "[" + ", ".join(marker_names) + "]"
    lines.append(
        f"mbs.AddObject(item_interface.CoordinateConstraint("
        f"name={_py_repr(driver.name)}, markerNumbers={marker_list}, "
        f"offset=0.0, offsetUserFunction=_driver_{safe_id}_offset, "
        f"offsetUserFunction_t=_driver_{safe_id}_offset_t))"
    )
    return lines


def _translation_driver(assembled: AssembledMechanism, driver, joint, safe_id: str) -> list[str]:
    lines: list[str] = []
    marker_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.MARKER else joint.endpoint_b
    slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
    body = assembled.bodies[marker_endpoint.body_id]
    marker = body.markers[marker_endpoint.marker_id]
    slider = assembled.sliders[slider_endpoint.slider_id]
    b = _safe_var(body.body_id)
    initial_m = (
        (marker.global_x - slider.origin_x) * slider.axis_x
        + (marker.global_y - slider.origin_y) * slider.axis_y
    ) * 1e-3
    lx_td, ly_td = _com_rel(body, marker)
    lines.append(
        f"rtm_{safe_id} = mbs.AddMarker(item_interface.MarkerBodiesRelativeTranslationCoordinate("
        f"bodyNumbers=[ground_object, body_{b}], "
        f"localPosition0=[{slider.origin_x * 1e-3}, {slider.origin_y * 1e-3}, 0.0], "
        f"localPosition1=[{lx_td * 1e-3}, {ly_td * 1e-3}, 0.0], "
        f"axis0=[{slider.axis_x}, {slider.axis_y}, 0.0], offset=0.0))"
    )
    lines.append(
        f"gn_{safe_id} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))"
    )
    lines.append(
        f"zm_{safe_id} = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=gn_{safe_id}, coordinate=0))"
    )
    lines.append(f"_td_init_{safe_id} = {initial_m!r}")
    lines.append(f"def _td_{safe_id}_offset(mbs, t, itemNumber, lOffset):")
    lines.append(f"    return -(_td_init_{safe_id} + _driver_{safe_id}_offset(mbs, t, itemNumber, lOffset))")
    lines.append(f"def _td_{safe_id}_offset_t(mbs, t, itemNumber, lOffset):")
    lines.append(f"    return -_driver_{safe_id}_offset_t(mbs, t, itemNumber, lOffset)")
    lines.append(
        f"mbs.AddObject(item_interface.CoordinateConstraint("
        f"name={_py_repr(driver.name)}, markerNumbers=[rtm_{safe_id}, zm_{safe_id}], offset=0.0, "
        f"offsetUserFunction=_td_{safe_id}_offset, "
        f"offsetUserFunction_t=_td_{safe_id}_offset_t))"
    )
    return lines


def _rotation_coordinate_markers(assembled: AssembledMechanism, joint) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    if joint.endpoint_a.kind is JointEndpointKind.MARKER and joint.endpoint_b.kind is JointEndpointKind.GROUND:
        body_id = joint.endpoint_a.body_id
        b = _safe_var(body_id)
        lines.append(f"rgn_{b} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))")
        lines.append(f"rgm_{b} = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=rgn_{b}, coordinate=0))")
        lines.append(
            f"rbm_{b} = mbs.AddMarker(item_interface.MarkerNodeCoordinate("
            f"nodeNumber=node_{b}, coordinate=2))"
        )
        return lines, [f"rgm_{b}", f"rbm_{b}"]
    if joint.endpoint_b.kind is JointEndpointKind.MARKER and joint.endpoint_a.kind is JointEndpointKind.GROUND:
        body_id = joint.endpoint_b.body_id
        b = _safe_var(body_id)
        lines.append(f"rgn_{b} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))")
        lines.append(f"rgm_{b} = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=rgn_{b}, coordinate=0))")
        lines.append(
            f"rbm_{b} = mbs.AddMarker(item_interface.MarkerNodeCoordinate("
            f"nodeNumber=node_{b}, coordinate=2))"
        )
        return lines, [f"rgm_{b}", f"rbm_{b}"]
    if joint.endpoint_a.kind is JointEndpointKind.MARKER and joint.endpoint_b.kind is JointEndpointKind.MARKER:
        a_id = joint.endpoint_a.body_id
        b_id = joint.endpoint_b.body_id
        a = _safe_var(a_id)
        bb = _safe_var(b_id)
        lines.append(
            f"ram_{a} = mbs.AddMarker(item_interface.MarkerNodeCoordinate("
            f"nodeNumber=node_{a}, coordinate=2))"
        )
        lines.append(
            f"rbm_{bb} = mbs.AddMarker(item_interface.MarkerNodeCoordinate("
            f"nodeNumber=node_{bb}, coordinate=2))"
        )
        return lines, [f"ram_{a}", f"rbm_{bb}"]
    raise ValueError(f"Rotation driver requires a revolute joint between marker-ground or marker-marker: {joint.name}")


def _find_body_for_marker(assembled: AssembledMechanism, marker_id: str) -> AssembledBody:
    for body in assembled.bodies.values():
        if marker_id in body.markers:
            return body
    raise ValueError(f"Marker {marker_id} not found in any body")


def _generate_loads(assembled: AssembledMechanism) -> list[str]:
    lines: list[str] = ["# --- Loads ---", ""]
    for load in assembled.loads:
        body = _find_body_for_marker(assembled, load.target_marker_id)
        marker = body.markers[load.target_marker_id]
        b = _safe_var(body.body_id)
        lm = _safe_var(f"lm_{load.load_id}")
        lx_load, ly_load = _com_rel(body, marker)
        lines.append(
            f"{lm} = mbs.AddMarker(item_interface.MarkerBodyRigid("
            f"bodyNumber=body_{b}, localPosition=[{lx_load * 1e-3}, {ly_load * 1e-3}, 0.0]))"
        )
        lines.append(
            f"mbs.AddLoad(item_interface.LoadForceVector("
            f"markerNumber={lm}, loadVector=[{load.fx}, {load.fy}, 0.0]))"
        )
    lines.append("")
    return lines


def _generate_springs(assembled: AssembledMechanism) -> list[str]:
    if not assembled.springs:
        return []
    lines: list[str] = ["# --- Springs / Actuators ---", ""]
    for s in assembled.springs:
        sv = _safe_var(s.spring_id)
        is_rotational = s.spring_type in ("rotational_spring", "rotational_actuator")
        is_actuator = s.spring_type in ("linear_actuator", "rotational_actuator")

        def _ep_marker(ep, suffix: str) -> str:
            if ep.kind == "ground":
                return (
                    f"mbs.AddMarker(item_interface.MarkerBodyPosition("
                    f"bodyNumber=ground_object, localPosition=[{ep.anchor_x * 1e-3}, {ep.anchor_y * 1e-3}, 0.0]))"
                )
            b = _safe_var(ep.body_id)
            return (
                f"mbs.AddMarker(item_interface.MarkerBodyPosition("
                f"bodyNumber=body_{b}, localPosition=[{ep.anchor_x * 1e-3}, {ep.anchor_y * 1e-3}, 0.0]))"
            )

        def _ep_angle(ep, suffix: str) -> str:
            if ep.kind == "ground":
                gn = f"gn_spring_{sv}_{suffix}"
                lines.append(f"{gn} = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))")
                return f"mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber={gn}, coordinate=0))"
            b = _safe_var(ep.body_id)
            return f"mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=node_{b}, coordinate=2))"

        if not is_rotational:
            lines.append(f"spm_a_{sv} = {_ep_marker(s.endpoint_a, 'a')}")
            lines.append(f"spm_b_{sv} = {_ep_marker(s.endpoint_b, 'b')}")
            if is_actuator:
                law_expr = s.law_expression or "0"
                lines.append(f"def _spring_law_{sv}(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):")
                lines.append(f"    # law: {law_expr}  (in N)")
                lines.append(f"    return 0.0  # TODO: evaluate {_py_repr(law_expr)} at t")
                lines.append(f"mbs.AddObject(item_interface.ObjectConnectorSpringDamper("
                             f"name={_py_repr(s.name)}, markerNumbers=[spm_a_{sv}, spm_b_{sv}], "
                             f"stiffness=0.0, damping=0.0, referenceLength=0.0, springForceUserFunction=_spring_law_{sv}))")
            else:
                k = s.stiffness * 1e3
                c = s.damping * 1e3
                L0 = s.rest_value * 1e-3
                lines.append(f"mbs.AddObject(item_interface.ObjectConnectorSpringDamper("
                             f"name={_py_repr(s.name)}, markerNumbers=[spm_a_{sv}, spm_b_{sv}], "
                             f"stiffness={k}, damping={c}, referenceLength={L0}))")
        else:
            lines.append(f"spm_a_{sv} = {_ep_angle(s.endpoint_a, 'a')}")
            lines.append(f"spm_b_{sv} = {_ep_angle(s.endpoint_b, 'b')}")
            if is_actuator:
                law_expr = s.law_expression or "0"
                lines.append(f"def _spring_law_{sv}(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):")
                lines.append(f"    # law: {law_expr}  (in N*mm)")
                lines.append(f"    return 0.0  # TODO: evaluate {_py_repr(law_expr)} at t")
                lines.append(f"mbs.AddObject(item_interface.ObjectConnectorCoordinateSpringDamper("
                             f"name={_py_repr(s.name)}, markerNumbers=[spm_a_{sv}, spm_b_{sv}], "
                             f"stiffness=0.0, damping=0.0, offset=0.0, springForceUserFunction=_spring_law_{sv}))")
            else:
                k = s.stiffness * 1e-3
                c = s.damping * 1e-3
                theta0 = s.rest_value
                lines.append(f"mbs.AddObject(item_interface.ObjectConnectorCoordinateSpringDamper("
                             f"name={_py_repr(s.name)}, markerNumbers=[spm_a_{sv}, spm_b_{sv}], "
                             f"stiffness={k}, damping={c}, offset={theta0}))")
        lines.append("")
    return lines


def generate_exudyn_script(
    project: Project,
    assembled: AssembledMechanism,
    duration: float,
    steps: int,
    expression_service: ExpressionService | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# Auto-generated by QUINO - Exudyn standalone script")
    lines.append("import math")
    lines.append("import exudyn")
    lines.append("import exudyn.itemInterface as item_interface")
    lines.append("import exudyn.graphics as gr")
    lines.append("")
    lines.extend(_generate_interp_helper())

    if expression_service is not None and assembled.drivers:
        lines.extend(_generate_driver_data(project, assembled, duration, steps, expression_service))

    lines.append("sc = exudyn.SystemContainer()")
    lines.append("mbs = sc.AddSystem()")
    lines.append("graphics_ground = [gr.Lines([[-0.5, -0.5, 0.0], [0.5, -0.5, 0.0], [0.0, 0.0, 0.0], [-0.5, -0.5, 0.0]], color=gr.color.darkgrey)]")
    lines.append("ground_object = mbs.AddObject(item_interface.ObjectGround(visualization=item_interface.VObjectGround(graphicsData=graphics_ground)))")
    lines.append("")
    lines.extend(_generate_bodies(project, assembled))
    lines.extend(_generate_joints(assembled))
    lines.extend(_generate_drivers(assembled))
    lines.extend(_generate_loads(assembled))
    lines.extend(_generate_springs(assembled))
    if assembled.gravity is not None:
        g = assembled.gravity
        lines.append(f"mbs.SetGravity([{g.magnitude * g.direction_x}, {g.magnitude * g.direction_y}, 0])")
    else:
        lines.append("mbs.SetGravity([0, 0, 0])")
    lines.append("mbs.Assemble()")
    lines.append("")
    lines.append("# --- Solve ---")
    lines.append("simulationSettings = exudyn.SimulationSettings()")
    lines.append(f"simulationSettings.timeIntegration.numberOfSteps = {steps}")
    lines.append(f"simulationSettings.timeIntegration.endTime = {duration}")
    lines.append("simulationSettings.solutionSettings.writeSolutionToFile = True")
    lines.append("simulationSettings.solutionSettings.coordinatesSolutionFileName = 'coordinatesSolution.txt'")
    lines.append(f"simulationSettings.solutionSettings.solutionWritePeriod = {duration / max(steps, 1)}")
    lines.append("if hasattr(simulationSettings.solutionSettings, 'binarySolutionFile'):")
    lines.append("    simulationSettings.solutionSettings.binarySolutionFile = False")
    lines.append("mbs.SolveDynamic(simulationSettings=simulationSettings)")
    lines.append("")
    lines.append("print('Simulation completed successfully')")
    lines.append("mbs.SolutionViewer()")

    return "\n".join(lines)
