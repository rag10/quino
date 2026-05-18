from __future__ import annotations

import math
from typing import Any

from quino.domain.model import (
    Driver,
    Joint,
    JointEndpoint,
    Project,
    ValidationMessage,
    ValidationReport,
)
from quino.domain.types import DriverType, JointEndpointKind
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService
from quino.simulation.sensor_expressions import sensor_expression_variables


class KinematicValidator:
    _ANGLE_LIMIT_POSITIVE_KEY = "angle_limit_positive_deg"
    _ANGLE_LIMIT_NEGATIVE_KEY = "angle_limit_negative_deg"

    def __init__(
        self,
        assembler: Any,
        expression_service: ExpressionService,
        unit_service: UnitService,
    ) -> None:
        self._assembler = assembler
        self._expression_service = expression_service
        self._unit_service = unit_service

    def validate_joint_geometry(self, project: Project, report: ValidationReport) -> None:
        try:
            assembled = self._assembler.assemble(project)
        except Exception as exc:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "geometry_assembly_failed",
                    f"Could not evaluate joint geometry: {exc}",
                )
            )
            return
        tolerance = 1e-6
        for joint in project.model.joints:
            endpoints = (joint.endpoint_a, joint.endpoint_b)
            marker_endpoints = [
                endpoint for endpoint in endpoints if endpoint.kind is JointEndpointKind.MARKER
            ]
            slider_endpoints = [
                endpoint for endpoint in endpoints if endpoint.kind is JointEndpointKind.SLIDER
            ]
            if len(marker_endpoints) == 2:
                first = self._assembled_marker(assembled, marker_endpoints[0])
                second = self._assembled_marker(assembled, marker_endpoints[1])
                if first is None or second is None:
                    continue
                gap = (
                    (first.global_x - second.global_x) ** 2
                    + (first.global_y - second.global_y) ** 2
                ) ** 0.5
                if gap > tolerance:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "joint_gap",
                            f"Joint {joint.name} marker-marker gap is {gap:.6g} mm",
                            joint.id,
                        )
                    )
                self._validate_joint_angle_limit(project, assembled, joint, report)
            elif (
                len(marker_endpoints) == 1
                and any(endpoint.kind is JointEndpointKind.GROUND for endpoint in endpoints)
            ):
                self._validate_joint_angle_limit(project, assembled, joint, report)
            elif len(marker_endpoints) == 1 and slider_endpoints:
                marker = self._assembled_marker(assembled, marker_endpoints[0])
                slider = assembled.sliders.get(slider_endpoints[0].slider_id)
                if marker is None or slider is None:
                    continue
                dx = marker.global_x - slider.origin_x
                dy = marker.global_y - slider.origin_y
                normal_gap = abs(dx * slider.normal_x + dy * slider.normal_y)
                slider_coordinate = dx * slider.axis_x + dy * slider.axis_y
                if normal_gap > tolerance:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "slider_joint_gap",
                            f"Joint {joint.name} marker-slider normal gap is {normal_gap:.6g} mm",
                            joint.id,
                        )
                    )
                if (
                    slider.travel_min is not None
                    and slider_coordinate < slider.travel_min - tolerance
                ):
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "slider_joint_travel",
                            (
                                f"Joint {joint.name} slider coordinate {slider_coordinate:.6g} mm "
                                f"is below travel_min {slider.travel_min:.6g} mm"
                            ),
                            joint.id,
                        )
                    )
                if (
                    slider.travel_max is not None
                    and slider_coordinate > slider.travel_max + tolerance
                ):
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "slider_joint_travel",
                            (
                                f"Joint {joint.name} slider coordinate {slider_coordinate:.6g} mm "
                                f"is above travel_max {slider.travel_max:.6g} mm"
                            ),
                            joint.id,
                        )
                    )

    def _assembled_marker(self, assembled, endpoint):
        if endpoint.body_id not in assembled.bodies:
            return None
        return assembled.bodies[endpoint.body_id].markers.get(endpoint.marker_id)

    def _validate_joint_angle_limit(self, project: Project, assembled, joint: Joint, report: ValidationReport) -> None:
        if joint.type.value != "revolute":
            return
        if joint.metadata.values.get("internal_ground_anchor"):
            return
        if any(endpoint.kind is JointEndpointKind.SLIDER for endpoint in (joint.endpoint_a, joint.endpoint_b)):
            return
        positive, negative = self._joint_angle_limit_values(joint)
        if positive is None and negative is None:
            return
        current = self._assembled_joint_relative_angle_deg(project, assembled, joint)
        if current is None:
            return
        lower = -(negative or 0.0)
        upper = positive or 0.0
        tolerance = 1e-6
        if current < lower - tolerance or current > upper + tolerance:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "joint_angle_limit",
                    (
                        f"Joint {joint.name} relative angle {current:.6g} deg is outside "
                        f"[{lower:.6g}, {upper:.6g}] deg from the model reference"
                    ),
                    joint.id,
                )
            )

    def _joint_angle_limit_values(self, joint: Joint) -> tuple[float | None, float | None]:
        def _coerce(key: str) -> float | None:
            raw = joint.metadata.values.get(key)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return None
            return value if value >= 0.0 else None

        return _coerce(self._ANGLE_LIMIT_POSITIVE_KEY), _coerce(self._ANGLE_LIMIT_NEGATIVE_KEY)

    def _assembled_joint_relative_angle_deg(self, project: Project, assembled, joint: Joint) -> float | None:
        if joint.endpoint_a.kind is JointEndpointKind.GROUND and joint.endpoint_b.kind is JointEndpointKind.MARKER:
            body = assembled.bodies.get(joint.endpoint_b.body_id or "")
            if body is None:
                return None
            return math.degrees(body.angle - self._model_body_reference_angle(project, joint.endpoint_b.body_id or ""))
        if joint.endpoint_b.kind is JointEndpointKind.GROUND and joint.endpoint_a.kind is JointEndpointKind.MARKER:
            body = assembled.bodies.get(joint.endpoint_a.body_id or "")
            if body is None:
                return None
            return math.degrees(body.angle - self._model_body_reference_angle(project, joint.endpoint_a.body_id or ""))
        if joint.endpoint_a.kind is not JointEndpointKind.MARKER or joint.endpoint_b.kind is not JointEndpointKind.MARKER:
            return None
        body_a = assembled.bodies.get(joint.endpoint_a.body_id or "")
        body_b = assembled.bodies.get(joint.endpoint_b.body_id or "")
        if body_a is None or body_b is None:
            return None
        domain_body_a = next((body for body in project.model.bodies if body.id == body_a.body_id), None)
        domain_body_b = next((body for body in project.model.bodies if body.id == body_b.body_id), None)
        if domain_body_a is not None and domain_body_a.metadata.values.get("ground_anchor") and domain_body_b is not None:
            return math.degrees(body_b.angle - self._model_body_reference_angle(project, body_b.body_id))
        if domain_body_b is not None and domain_body_b.metadata.values.get("ground_anchor") and domain_body_a is not None:
            return math.degrees(body_a.angle - self._model_body_reference_angle(project, body_a.body_id))
        current_rel = body_b.angle - body_a.angle
        model_rel = (
            self._model_body_reference_angle(project, body_b.body_id)
            - self._model_body_reference_angle(project, body_a.body_id)
        )
        return math.degrees(current_rel - model_rel)

    def _model_body_reference_angle(self, project: Project, body_id: str) -> float:
        for body in project.model.bodies:
            if body.id == body_id:
                markers = body.structural_markers()
                if len(markers) >= 2:
                    try:
                        x1 = self._expression_service.evaluate_property(markers[0].x, project.parameters).value
                        y1 = self._expression_service.evaluate_property(markers[0].y, project.parameters).value
                        x2 = self._expression_service.evaluate_property(markers[1].x, project.parameters).value
                        y2 = self._expression_service.evaluate_property(markers[1].y, project.parameters).value
                    except Exception:
                        return 0.0
                    return math.atan2(y2 - y1, x2 - x1)
                return 0.0
        return 0.0

    def validate_kinematic_reach(
        self,
        project: Project,
        report: ValidationReport,
        duration: float,
        steps: int,
    ) -> None:
        try:
            assembled = self._assembler.assemble(project)
        except Exception:
            return
        sample_times = self.simulation_sample_times(duration, steps)
        self.validate_translation_driver_travel(project, report, assembled, sample_times)
        reported: set[tuple[str, str, str]] = set()
        for driver in project.model.drivers:
            if driver.type is not DriverType.ROTATION:
                continue
            try:
                driven_joint = self._find_joint(project, driver.target_joint_id)
            except ValueError:
                continue
            grounded_endpoint = self._marker_ground_endpoint(driven_joint)
            if grounded_endpoint is None or grounded_endpoint.body_id is None:
                continue
            driven_body = assembled.bodies.get(grounded_endpoint.body_id)
            if driven_body is None or grounded_endpoint.marker_id is None:
                continue
            ground_marker = driven_body.markers.get(grounded_endpoint.marker_id)
            if ground_marker is None:
                continue
            for joint in project.model.joints:
                if joint.id == driven_joint.id:
                    continue
                marker_endpoints = [
                    endpoint
                    for endpoint in (joint.endpoint_a, joint.endpoint_b)
                    if endpoint.kind is JointEndpointKind.MARKER
                ]
                if len(marker_endpoints) != 2:
                    continue
                driven_endpoints = [
                    endpoint
                    for endpoint in marker_endpoints
                    if endpoint.body_id == driven_body.body_id
                ]
                follower_endpoints = [
                    endpoint for endpoint in marker_endpoints if endpoint.body_id != driven_body.body_id
                ]
                for driven_endpoint in driven_endpoints:
                    if driven_endpoint.marker_id is None:
                        continue
                    driven_marker = driven_body.markers.get(driven_endpoint.marker_id)
                    if driven_marker is None:
                        continue
                    for follower_endpoint in follower_endpoints:
                        if follower_endpoint.body_id is None or follower_endpoint.marker_id is None:
                            continue
                        follower_body = assembled.bodies.get(follower_endpoint.body_id)
                        if follower_body is None:
                            continue
                        follower_marker = follower_body.markers.get(follower_endpoint.marker_id)
                        if follower_marker is None:
                            continue
                        slider_links = self._slider_links_for_body(
                            project,
                            follower_endpoint.body_id,
                            exclude_marker_id=follower_endpoint.marker_id,
                        )
                        for slider_joint, slider_marker_endpoint, slider_endpoint in slider_links:
                            key = (driver.id, joint.id, slider_joint.id)
                            if key in reported:
                                continue
                            slider = assembled.sliders.get(slider_endpoint.slider_id)
                            slider_marker = follower_body.markers.get(slider_marker_endpoint.marker_id)
                            if slider is None or slider_marker is None:
                                continue
                            reach = (
                                (slider_marker.local_x - follower_marker.local_x) ** 2
                                + (slider_marker.local_y - follower_marker.local_y) ** 2
                            ) ** 0.5
                            failure = self._first_slider_reach_failure(
                                project,
                                driver,
                                driven_body,
                                ground_marker,
                                driven_marker,
                                slider,
                                reach,
                                sample_times,
                            )
                            if failure is None:
                                continue
                            reported.add(key)
                            report.messages.append(
                                ValidationMessage(
                                    "warning",
                                    failure[0],
                                    failure[1],
                                    slider_joint.id,
                                )
                            )

        self.validate_rotational_loop_reach(project, report, assembled, sample_times)

    def validate_translation_driver_travel(
        self,
        project: Project,
        report: ValidationReport,
        assembled,
        sample_times: list[float],
    ) -> None:
        reported: set[str] = set()
        for driver in project.model.drivers:
            if driver.type is not DriverType.TRANSLATION:
                continue
            try:
                joint = self._find_joint(project, driver.target_joint_id)
            except ValueError:
                continue
            marker_endpoint, slider_endpoint = self._marker_slider_endpoints(joint)
            if (
                marker_endpoint is None
                or slider_endpoint is None
                or marker_endpoint.body_id is None
                or marker_endpoint.marker_id is None
                or slider_endpoint.slider_id is None
            ):
                continue
            body = assembled.bodies.get(marker_endpoint.body_id)
            slider = assembled.sliders.get(slider_endpoint.slider_id)
            if body is None or slider is None:
                continue
            marker = body.markers.get(marker_endpoint.marker_id)
            if marker is None:
                continue
            initial_coordinate = (
                (marker.global_x - slider.origin_x) * slider.axis_x
                + (marker.global_y - slider.origin_y) * slider.axis_y
            )
            for time_value in sample_times:
                try:
                    target_coordinate = initial_coordinate + self._driver_value_at(
                        driver,
                        project,
                        time_value,
                        "mm",
                    )
                except Exception:
                    break
                if slider.travel_min is not None and target_coordinate < slider.travel_min - 1e-6:
                    if driver.id not in reported:
                        reported.add(driver.id)
                        report.messages.append(
                            ValidationMessage(
                                "warning",
                                "kinematic_travel",
                                (
                                    f"Driver {driver.name} requests slider {slider.name} coordinate "
                                    f"{target_coordinate:.6g} mm at t={time_value:.3g}s, below "
                                    f"travel_min {slider.travel_min:.6g} mm"
                                ),
                                joint.id,
                            )
                        )
                    break
                if slider.travel_max is not None and target_coordinate > slider.travel_max + 1e-6:
                    if driver.id not in reported:
                        reported.add(driver.id)
                        report.messages.append(
                            ValidationMessage(
                                "warning",
                                "kinematic_travel",
                                (
                                    f"Driver {driver.name} requests slider {slider.name} coordinate "
                                    f"{target_coordinate:.6g} mm at t={time_value:.3g}s, above "
                                    f"travel_max {slider.travel_max:.6g} mm"
                                ),
                                joint.id,
                            )
                        )
                    break

    def validate_rotational_loop_reach(
        self,
        project: Project,
        report: ValidationReport,
        assembled,
        sample_times: list[float],
    ) -> None:
        reported: set[tuple[str, str, str, str]] = set()
        for driver in project.model.drivers:
            if driver.type is not DriverType.ROTATION:
                continue
            try:
                driven_joint = self._find_joint(project, driver.target_joint_id)
            except ValueError:
                continue
            grounded_endpoint = self._marker_ground_endpoint(driven_joint)
            if grounded_endpoint is None or grounded_endpoint.body_id is None:
                continue
            driven_body = assembled.bodies.get(grounded_endpoint.body_id)
            if driven_body is None or grounded_endpoint.marker_id is None:
                continue
            ground_marker = driven_body.markers.get(grounded_endpoint.marker_id)
            if ground_marker is None:
                continue
            for input_joint in project.model.joints:
                if input_joint.id == driven_joint.id:
                    continue
                input_endpoints = self._marker_marker_endpoints(input_joint)
                if input_endpoints is None:
                    continue
                driven_endpoint = next(
                    (
                        endpoint
                        for endpoint in input_endpoints
                        if endpoint.body_id == driven_body.body_id
                    ),
                    None,
                )
                follower_endpoint = next(
                    (
                        endpoint
                        for endpoint in input_endpoints
                        if endpoint.body_id != driven_body.body_id
                    ),
                    None,
                )
                if (
                    driven_endpoint is None
                    or follower_endpoint is None
                    or driven_endpoint.marker_id is None
                    or follower_endpoint.body_id is None
                    or follower_endpoint.marker_id is None
                ):
                    continue
                driven_marker = driven_body.markers.get(driven_endpoint.marker_id)
                follower_body = assembled.bodies.get(follower_endpoint.body_id)
                if driven_marker is None or follower_body is None:
                    continue
                follower_input_marker = follower_body.markers.get(follower_endpoint.marker_id)
                if follower_input_marker is None:
                    continue
                for output_joint in project.model.joints:
                    if output_joint.id in {driven_joint.id, input_joint.id}:
                        continue
                    output_endpoints = self._marker_marker_endpoints(output_joint)
                    if output_endpoints is None:
                        continue
                    follower_output_endpoint = next(
                        (
                            endpoint
                            for endpoint in output_endpoints
                            if (
                                endpoint.body_id == follower_body.body_id
                                and endpoint.marker_id != follower_endpoint.marker_id
                            )
                        ),
                        None,
                    )
                    terminal_endpoint = next(
                        (
                            endpoint
                            for endpoint in output_endpoints
                            if endpoint.body_id != follower_body.body_id
                        ),
                        None,
                    )
                    if (
                        follower_output_endpoint is None
                        or terminal_endpoint is None
                        or follower_output_endpoint.marker_id is None
                        or terminal_endpoint.body_id is None
                        or terminal_endpoint.marker_id is None
                    ):
                        continue
                    terminal_body = assembled.bodies.get(terminal_endpoint.body_id)
                    if terminal_body is None:
                        continue
                    follower_output_marker = follower_body.markers.get(
                        follower_output_endpoint.marker_id
                    )
                    terminal_output_marker = terminal_body.markers.get(terminal_endpoint.marker_id)
                    if follower_output_marker is None or terminal_output_marker is None:
                        continue
                    terminal_ground = self._ground_endpoint_for_body(
                        project,
                        terminal_body.body_id,
                        exclude_marker_id=terminal_endpoint.marker_id,
                    )
                    if terminal_ground is None or terminal_ground.marker_id is None:
                        continue
                    terminal_ground_marker = terminal_body.markers.get(terminal_ground.marker_id)
                    if terminal_ground_marker is None:
                        continue
                    key = (driver.id, input_joint.id, output_joint.id, terminal_ground.marker_id)
                    if key in reported:
                        continue
                    follower_length = self._local_distance(
                        follower_input_marker,
                        follower_output_marker,
                    )
                    terminal_length = self._local_distance(
                        terminal_ground_marker,
                        terminal_output_marker,
                    )
                    failure = self._first_four_bar_reach_failure(
                        project,
                        driver,
                        driven_body,
                        ground_marker,
                        driven_marker,
                        terminal_ground_marker,
                        follower_length,
                        terminal_length,
                        sample_times,
                    )
                    if failure is None:
                        continue
                    reported.add(key)
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "kinematic_loop_reach",
                            failure,
                            output_joint.id,
                        )
                    )

    def _first_four_bar_reach_failure(
        self,
        project: Project,
        driver: Driver,
        driven_body,
        ground_marker,
        driven_marker,
        terminal_ground_marker,
        follower_length: float,
        terminal_length: float,
        sample_times: list[float],
    ) -> str | None:
        tolerance = 1e-6
        minimum = abs(follower_length - terminal_length)
        maximum = follower_length + terminal_length
        for time_value in sample_times:
            try:
                driver_angle = self._driver_value_at(driver, project, time_value, "rad")
            except Exception:
                return None
            marker_x, marker_y = self._driven_marker_position(
                driven_body,
                ground_marker,
                driven_marker,
                driver_angle,
            )
            distance = (
                (marker_x - terminal_ground_marker.global_x) ** 2
                + (marker_y - terminal_ground_marker.global_y) ** 2
            ) ** 0.5
            if distance > maximum + tolerance or distance < minimum - tolerance:
                return (
                    f"Driver {driver.name} may make the closed loop unreachable at "
                    f"t={time_value:.3g}s: distance between driven joint and fixed rocker "
                    f"ground is {distance:.6g} mm, but the connected links require "
                    f"{minimum:.6g} mm <= distance <= {maximum:.6g} mm"
                )
        return None

    def _first_slider_reach_failure(
        self,
        project: Project,
        driver: Driver,
        driven_body,
        ground_marker,
        driven_marker,
        slider,
        reach: float,
        sample_times: list[float],
    ) -> tuple[str, str] | None:
        tolerance = 1e-6
        for time_value in sample_times:
            try:
                driver_angle = self._driver_value_at(driver, project, time_value, "rad")
            except Exception:
                return None
            marker_x, marker_y = self._driven_marker_position(
                driven_body,
                ground_marker,
                driven_marker,
                driver_angle,
            )
            dx = marker_x - slider.origin_x
            dy = marker_y - slider.origin_y
            normal_distance = abs(dx * slider.normal_x + dy * slider.normal_y)
            if normal_distance > reach + tolerance:
                return (
                    "kinematic_reach",
                    (
                        f"Driver {driver.name} may make the mechanism unreachable at "
                        f"t={time_value:.3g}s: driven joint is {normal_distance:.6g} mm "
                        f"from slider {slider.name}, but connected body reach is {reach:.6g} mm"
                    ),
                )
            slider_coordinate = dx * slider.axis_x + dy * slider.axis_y
            half_chord = max(reach**2 - normal_distance**2, 0.0) ** 0.5
            min_possible = slider_coordinate - half_chord
            max_possible = slider_coordinate + half_chord
            if slider.travel_min is not None and max_possible < slider.travel_min - tolerance:
                return (
                    "kinematic_travel",
                    (
                        f"Driver {driver.name} may move beyond slider {slider.name} travel at "
                        f"t={time_value:.3g}s: reachable slider coordinate is at most "
                        f"{max_possible:.6g} mm, below travel_min {slider.travel_min:.6g} mm"
                    ),
                )
            if slider.travel_max is not None and min_possible > slider.travel_max + tolerance:
                return (
                    "kinematic_travel",
                    (
                        f"Driver {driver.name} may move beyond slider {slider.name} travel at "
                        f"t={time_value:.3g}s: reachable slider coordinate is at least "
                        f"{min_possible:.6g} mm, above travel_max {slider.travel_max:.6g} mm"
                    ),
                )
        return None

    def simulation_sample_times(self, duration: float, steps: int) -> list[float]:
        count = max(2, min(max(steps, 1) + 1, 80))
        return [duration * index / (count - 1) for index in range(count)]

    def _marker_ground_endpoint(self, joint: Joint) -> JointEndpoint | None:
        endpoints = (joint.endpoint_a, joint.endpoint_b)
        if not any(endpoint.kind is JointEndpointKind.GROUND for endpoint in endpoints):
            return None
        for endpoint in endpoints:
            if endpoint.kind is JointEndpointKind.MARKER:
                return endpoint
        return None

    def _marker_marker_endpoints(self, joint: Joint) -> tuple[JointEndpoint, JointEndpoint] | None:
        if (
            joint.endpoint_a.kind is JointEndpointKind.MARKER
            and joint.endpoint_b.kind is JointEndpointKind.MARKER
        ):
            return joint.endpoint_a, joint.endpoint_b
        return None

    def _ground_endpoint_for_body(
        self,
        project: Project,
        body_id: str,
        exclude_marker_id: str,
    ) -> JointEndpoint | None:
        for joint in project.model.joints:
            marker_endpoint = self._marker_ground_endpoint(joint)
            if (
                marker_endpoint is not None
                and marker_endpoint.body_id == body_id
                and marker_endpoint.marker_id != exclude_marker_id
            ):
                return marker_endpoint
        return None

    def _local_distance(self, first, second) -> float:
        return ((first.local_x - second.local_x) ** 2 + (first.local_y - second.local_y) ** 2) ** 0.5

    def _slider_links_for_body(
        self,
        project: Project,
        body_id: str,
        exclude_marker_id: str,
    ) -> list[tuple[Joint, JointEndpoint, JointEndpoint]]:
        links: list[tuple[Joint, JointEndpoint, JointEndpoint]] = []
        for joint in project.model.joints:
            marker_endpoint = None
            slider_endpoint = None
            for endpoint in (joint.endpoint_a, joint.endpoint_b):
                if (
                    endpoint.kind is JointEndpointKind.MARKER
                    and endpoint.body_id == body_id
                    and endpoint.marker_id != exclude_marker_id
                ):
                    marker_endpoint = endpoint
                elif endpoint.kind is JointEndpointKind.SLIDER:
                    slider_endpoint = endpoint
            if marker_endpoint is not None and slider_endpoint is not None:
                links.append((joint, marker_endpoint, slider_endpoint))
        return links

    def _driver_value_at(
        self,
        driver: Driver,
        project: Project,
        time_value: float,
        unit: str,
    ) -> float:
        quantity = self._expression_service.evaluate_expression(
            driver.law.expression,
            project.parameters,
            variables={"t": self._unit_service.quantity(time_value, "s")},
        )
        return self._unit_service.convert(quantity, unit)

    def load_expression_variables(
        self,
        project: Project,
        *,
        time_value: float = 0.0,
    ) -> dict[str, object]:
        assembled = self._assembler.assemble(project)
        frame: dict[str, float] = {}
        for body_id, body in assembled.bodies.items():
            frame[f"{body_id}.x"] = body.origin_x
            frame[f"{body_id}.y"] = body.origin_y
            frame[f"{body_id}.angle"] = body.angle
        variables = {"t": self._unit_service.quantity(time_value, "s")}
        variables.update(sensor_expression_variables(project, assembled, frame, self._unit_service))
        return variables

    def _driven_marker_position(self, body, ground_marker, driven_marker, driver_angle: float) -> tuple[float, float]:
        absolute_angle = body.angle + driver_angle
        cos_a = math.cos(absolute_angle)
        sin_a = math.sin(absolute_angle)
        origin_x = ground_marker.global_x - (
            cos_a * ground_marker.local_x - sin_a * ground_marker.local_y
        )
        origin_y = ground_marker.global_y - (
            sin_a * ground_marker.local_x + cos_a * ground_marker.local_y
        )
        return (
            origin_x + cos_a * driven_marker.local_x - sin_a * driven_marker.local_y,
            origin_y + sin_a * driven_marker.local_x + cos_a * driven_marker.local_y,
        )

    @staticmethod
    def _find_joint(project: Project, joint_id: str) -> Joint:
        for joint in project.model.joints:
            if joint.id == joint_id:
                return joint
        raise ValueError(f"Unknown joint: {joint_id}")

    @staticmethod
    def _marker_slider_endpoints(joint: Joint) -> tuple[JointEndpoint | None, JointEndpoint | None]:
        marker_endpoint = None
        slider_endpoint = None
        for endpoint in (joint.endpoint_a, joint.endpoint_b):
            if endpoint.kind is JointEndpointKind.MARKER:
                marker_endpoint = endpoint
            elif endpoint.kind is JointEndpointKind.SLIDER:
                slider_endpoint = endpoint
        return marker_endpoint, slider_endpoint
