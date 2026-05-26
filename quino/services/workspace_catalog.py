from __future__ import annotations

from quino.domain.model import ScalarProperty, Spring
from quino.domain.types import SpringType
from quino.domain.workspace import ParameterDescriptor


def build_parameter_catalog(project) -> dict[str, ParameterDescriptor]:
    """Derive a workspace parameter catalog from the current project model.

    The default tagging is intentionally conservative:
    - design-defining values are `invariant`
    - command/operating/control values are `variable`
    """
    catalog: dict[str, ParameterDescriptor] = {}

    for parameter in project.parameters:
        path = f"parameters/{parameter.id}"
        catalog[path] = ParameterDescriptor(
            path=path,
            tag="invariant",
            display_name=parameter.name,
            unit=parameter.unit,
            entity_id=parameter.id,
            property_name="expression",
        )

    for body in project.model.bodies:
        if body.mass is not None:
            _add_scalar_descriptor(
                catalog,
                path=f"bodies/{body.id}/mass",
                display_name=f"{body.name} mass",
                scalar=body.mass,
                tag="invariant",
                entity_id=body.id,
                property_name="mass",
            )

    for load in project.model.loads:
        _add_scalar_descriptor(
            catalog,
            path=f"loads/{load.id}/fx",
            display_name=f"{load.name} Fx",
            scalar=load.fx,
            tag="invariant",
            entity_id=load.id,
            property_name="fx",
        )
        _add_scalar_descriptor(
            catalog,
            path=f"loads/{load.id}/fy",
            display_name=f"{load.name} Fy",
            scalar=load.fy,
            tag="invariant",
            entity_id=load.id,
            property_name="fy",
        )

    for spring in project.model.springs:
        if spring.rest_value is not None:
            _add_scalar_descriptor(
                catalog,
                path=f"springs/{spring.id}/rest_value",
                display_name=f"{spring.name} rest value",
                scalar=spring.rest_value,
                tag="invariant",
                entity_id=spring.id,
                property_name="rest_value",
            )
        if spring.law is not None:
            _add_scalar_descriptor(
                catalog,
                path=f"springs/{spring.id}/law",
                display_name=f"{spring.name} law",
                scalar=spring.law,
                tag="variable",
                entity_id=spring.id,
                property_name="law",
            )
        catalog[f"springs/{spring.id}/stiffness"] = ParameterDescriptor(
            path=f"springs/{spring.id}/stiffness",
            tag="invariant",
            display_name=f"{spring.name} stiffness",
            entity_id=spring.id,
            property_name="stiffness",
        )
        catalog[f"springs/{spring.id}/damping"] = ParameterDescriptor(
            path=f"springs/{spring.id}/damping",
            tag="invariant",
            display_name=f"{spring.name} damping",
            entity_id=spring.id,
            property_name="damping",
        )
        if spring.spring_type in (SpringType.LINEAR_ACTUATOR, SpringType.ROTATIONAL_ACTUATOR):
            _retag(catalog, f"springs/{spring.id}/stiffness", "variable")
            _retag(catalog, f"springs/{spring.id}/damping", "variable")

    for driver in project.model.drivers:
        _add_scalar_descriptor(
            catalog,
            path=f"drivers/{driver.id}/law",
            display_name=f"{driver.name} law",
            scalar=driver.law,
            tag="variable",
            entity_id=driver.id,
            property_name="law",
        )

    control_graph = project.model.control_graph
    if control_graph is not None:
        for instance_id, instance in control_graph.instances.items():
            for key, value in instance.parameters.items():
                if key.startswith("_"):
                    continue
                path = f"model/control_graph/instances/{instance_id}/parameters/{key}"
                catalog[path] = ParameterDescriptor(
                    path=path,
                    tag="variable",
                    display_name=f"{instance_id}.{key}",
                    default_value=_coerce_float(value),
                    entity_id=instance_id,
                    property_name=key,
                )
                legacy_path = f"block_diagram/instances/{instance_id}/parameters/{key}"
                catalog[legacy_path] = ParameterDescriptor(
                    path=legacy_path,
                    tag="variable",
                    display_name=f"{instance_id}.{key}",
                    default_value=_coerce_float(value),
                    entity_id=instance_id,
                    property_name=key,
                )

    return catalog


def _add_scalar_descriptor(
    catalog: dict[str, ParameterDescriptor],
    *,
    path: str,
    display_name: str,
    scalar: ScalarProperty,
    tag: str,
    entity_id: str,
    property_name: str,
) -> None:
    catalog[path] = ParameterDescriptor(
        path=path,
        tag=tag,
        display_name=display_name,
        unit=scalar.unit,
        dimension=scalar.expected_dimension.value,
        entity_id=entity_id,
        property_name=property_name,
    )


def _retag(catalog: dict[str, ParameterDescriptor], path: str, tag: str) -> None:
    descriptor = catalog.get(path)
    if descriptor is not None:
        descriptor.tag = tag


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
