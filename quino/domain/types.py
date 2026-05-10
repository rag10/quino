from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class BodyType(StrEnum):
    BODY = "body"
    BAR = "bar"
    POINT_MASS = "point_mass"


class MarkerType(StrEnum):
    STRUCTURAL = "structural"
    COM = "com"


class JointType(StrEnum):
    REVOLUTE = "revolute"
    RIGID = "rigid"


class JointEndpointKind(StrEnum):
    MARKER = "marker"
    GROUND = "ground"
    SLIDER = "slider"


class Dimension(StrEnum):
    LENGTH = "length"
    ANGLE = "angle"
    MASS = "mass"
    INERTIA = "inertia"
    TIME = "time"
    UNITLESS = "unitless"


class DriverType(StrEnum):
    ROTATION = "rotation"
    TRANSLATION = "translation"


class SensorType(StrEnum):
    POINT = "point"
    DISTANCE = "distance"
    ANGLE_HORIZONTAL = "angle_horizontal"
    ANGLE_VERTICAL = "angle_vertical"
    ANGLE_VECTOR = "angle_vector"


class SketchEntityType(StrEnum):
    POINT = "point"
    LINE_SEGMENT = "line_segment"
    CIRCLE = "circle"
    ARC = "arc"
    INFINITE_LINE = "infinite_line"


class SketchConstraintType(StrEnum):
    FIX = "fix"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    DISTANCE = "distance"
    COINCIDENT = "coincident"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    EQUAL_LENGTH = "equal_length"
    ANGLE = "angle"
    MIDPOINT = "midpoint"
    COLLINEAR = "collinear"
    SYMMETRIC = "symmetric"
    ON_CIRCLE = "on_circle"
    TANGENT = "tangent"
