"""Resolve feature coordinates and dependency IDs for constructions and DXF."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Literal

from .construction_geom import (
    circle_circle_intersections_2d,
    circle_line_intersections_2d,
    ellipse_ellipse_intersections_2d,
    ellipse_line_intersections_2d,
    tangent_circle_to_circle_external_2d,
    tangent_ellipse_to_ellipse_external_2d,
    tangent_point_to_circle_2d,
    tangent_point_to_ellipse_2d,
)
from .coordinate_transform import mcs_xyz_to_wcs_xyz
from .gcode_m118 import PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y, PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y
from .session import CoordSys, FeatureKind, ProbeScanFeature

_ERROR_INCOMPLETE_DATA = "Probe returned incomplete bore/boss data."
_ERROR_INVALID_MISSING_DIAMETER = "Invalid or missing bore diameter."

XY = tuple[float, float]
CurveKind = Literal["circle", "ellipse"]
Curve = tuple[CurveKind, tuple[float, ...]]
TangentLine = tuple[XY, XY]


def index_by_id(features: Iterable[ProbeScanFeature]) -> dict[str, ProbeScanFeature]:
    return {f.id: f for f in features}


def diameters_equal(
    diameter_x: float,
    diameter_y: float,
    *,
    tolerance_mm: float,
) -> bool:
    """True when probed X/Y diameters represent a round bore within tolerance."""
    return abs(float(diameter_x) - float(diameter_y)) <= float(tolerance_mm)


def payload_referenced_feature_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("a_id", "b_id", "segment_a_id", "segment_b_id",
                "point_id", "circle_id", "circle_a_id", "circle_b_id"):
        v = payload.get(key)
        if v:
            ids.append(str(v))
    verts = payload.get("vertex_feature_ids")
    if isinstance(verts, list):
        ids.extend(str(v) for v in verts if v)
    src = payload.get("source_ids")
    if isinstance(src, list):
        ids.extend(str(v) for v in src if v)
    return ids


def referenced_feature_ids(feature: ProbeScanFeature) -> list[str]:
    return payload_referenced_feature_ids(feature.payload)


def features_referencing_id(features: Iterable[ProbeScanFeature], target_id: str) -> list[str]:
    holders: list[str] = []
    for i, f in enumerate(features):
        if target_id in referenced_feature_ids(f):
            holders.append(f"{i + 1}. {f.label}")
    return holders


def resolve_xy(vertex: ProbeScanFeature) -> XY | None:
    """Vertices for constructions: POINT, CORNER, curve centers, DERIVED_POINT."""
    p = vertex.payload
    if vertex.kind == FeatureKind.POINT:
        return float(p["x"]), float(p["y"])
    if vertex.kind == FeatureKind.CORNER:
        return float(p["x"]), float(p["y"])
    if vertex.kind in (FeatureKind.CIRCLE, FeatureKind.ELLIPSE, FeatureKind.DERIVED_CIRCLE):
        return float(p["cx"]), float(p["cy"])
    if vertex.kind == FeatureKind.DERIVED_POINT:
        return float(p["x"]), float(p["y"])
    return None


def segment_endpoints(
    by_id: dict[str, ProbeScanFeature],
    seg: ProbeScanFeature,
    resolve: Callable[[ProbeScanFeature], XY | None] = resolve_xy,
) -> tuple[XY, XY] | None:
    """Return ((x1,y1),(x2,y2)) for a SEGMENT feature."""
    if seg.kind != FeatureKind.SEGMENT:
        return None
    a = by_id.get(str(seg.payload.get("a_id", "")))
    b = by_id.get(str(seg.payload.get("b_id", "")))
    if not a or not b:
        return None
    pa = resolve(a)
    pb = resolve(b)
    if pa is None or pb is None:
        return None
    return pa, pb


def resolve_circle(feature: ProbeScanFeature) -> tuple[float, float, float] | None:
    """Return (cx, cy, r) for CIRCLE or DERIVED_CIRCLE features, else None."""
    p = feature.payload
    if feature.kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE):
        return (
            float(p.get("cx", 0.0)),
            float(p.get("cy", 0.0)),
            float(p.get("r", 0.0)),
        )

    return None


def resolve_ellipse(feature: ProbeScanFeature) -> tuple[float, float, float, float] | None:
    """Return (cx, cy, rx, ry) for ELLIPSE features, else None."""
    if feature.kind != FeatureKind.ELLIPSE:
        return None
    p = feature.payload
    return (
        float(p.get("cx", 0.0)),
        float(p.get("cy", 0.0)),
        float(p.get("diameter_x", 0.0)) / 2.0,
        float(p.get("diameter_y", 0.0)) / 2.0,
    )


def resolve_curve(feature: ProbeScanFeature) -> Curve | None:
    """Return ('circle', (cx,cy,r)) or ('ellipse', (cx,cy,rx,ry)) for curve features."""
    circ = resolve_circle(feature)
    if circ is not None:
        return ("circle", circ)
    ell = resolve_ellipse(feature)
    if ell is not None:
        return ("ellipse", ell)
    return None


def curve_to_ellipse_params(curve: Curve) -> tuple[float, float, float, float]:
    """Normalize circle or ellipse curve tuple to (cx, cy, rx, ry)."""
    kind, data = curve
    if kind == "circle":
        cx, cy, r = data
        return float(cx), float(cy), float(r), float(r)
    cx, cy, rx, ry = data
    return float(cx), float(cy), float(rx), float(ry)


def curve_line_intersections(
    curve: Curve,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> list[XY]:
    """Intersections of a circle or ellipse with the infinite line through A and B."""
    kind, data = curve
    if kind == "circle":
        return circle_line_intersections_2d(data[0], data[1], data[2], ax, ay, bx, by)
    cx, cy, rx, ry = curve_to_ellipse_params(curve)
    return ellipse_line_intersections_2d(cx, cy, rx, ry, ax, ay, bx, by)


def curve_curve_intersections(c1: Curve, c2: Curve) -> list[XY]:
    """Intersections of two circles or ellipses."""
    if c1[0] == "circle" and c2[0] == "circle":
        return circle_circle_intersections_2d(*c1[1], *c2[1])
    e1 = curve_to_ellipse_params(c1)
    e2 = curve_to_ellipse_params(c2)
    return ellipse_ellipse_intersections_2d(*e1, *e2)


def point_curve_tangents(px: float, py: float, curve: Curve) -> list[XY]:
    """Tangent touch-points on a circle or ellipse from an external point."""
    kind, data = curve
    if kind == "circle":
        return tangent_point_to_circle_2d(px, py, data[0], data[1], data[2])
    ecx, ecy, erx, ery = curve_to_ellipse_params(curve)
    return tangent_point_to_ellipse_2d(px, py, ecx, ecy, erx, ery)


def curve_curve_external_tangents(c1: Curve, c2: Curve) -> list[TangentLine]:
    """External tangent lines between two circles or ellipses."""
    if c1[0] == "circle" and c2[0] == "circle":
        return tangent_circle_to_circle_external_2d(*c1[1], *c2[1])
    e1 = curve_to_ellipse_params(c1)
    e2 = curve_to_ellipse_params(c2)
    return tangent_ellipse_to_ellipse_external_2d(*e1, *e2)


def feature_from_m461_m462(
    label: str,
    vd: dict[str, float],
    var_keys: list[str],
    *,
    mx: float,
    my: float,
    tolerance_mm: float = 0.01,
) -> tuple[ProbeScanFeature | None, str | None]:
    """
    Build a CIRCLE or ELLIPSE feature from M461/M462 probe variables.

    Returns (feature, error_message). Exactly one of the tuple elements is non-None.
    Branches on captured var_keys (not UI preset).
    """
    keys = {str(k).strip() for k in var_keys if str(k).strip()}

    if keys == {PROBE_VAR_DIA_X, PROBE_VAR_CENTER_X}:
        if PROBE_VAR_DIA_X not in vd or PROBE_VAR_CENTER_X not in vd:
            return None, _ERROR_INCOMPLETE_DATA
        d_x = float(vd[PROBE_VAR_DIA_X])
        if d_x <= 0:
            return None, _ERROR_INVALID_MISSING_DIAMETER
        cx_m = float(vd[PROBE_VAR_CENTER_X])
        cy_m = float(vd[PROBE_VAR_CENTER_Y]) if PROBE_VAR_CENTER_Y in vd else float(my)
        wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
        return (
            ProbeScanFeature.new_circle(
                label, wx, wy, d_x / 2.0, coord_sys=CoordSys.WCS
            ),
            None,
        )

    if keys == {PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_Y}:
        if PROBE_VAR_DIA_Y not in vd or PROBE_VAR_CENTER_Y not in vd:
            return None, _ERROR_INCOMPLETE_DATA
        d_y = float(vd[PROBE_VAR_DIA_Y])
        if d_y <= 0:
            return None, _ERROR_INVALID_MISSING_DIAMETER
        cy_m = float(vd[PROBE_VAR_CENTER_Y])
        cx_m = float(vd[PROBE_VAR_CENTER_X]) if PROBE_VAR_CENTER_X in vd else float(mx)
        wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
        return (
            ProbeScanFeature.new_circle(
                label, wx, wy, d_y / 2.0, coord_sys=CoordSys.WCS
            ),
            None,
        )

    if keys == {PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y}:
        if not all(
            k in vd
            for k in (PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y)
        ):
            return None, _ERROR_INCOMPLETE_DATA
        d_x = float(vd[PROBE_VAR_DIA_X])
        d_y = float(vd[PROBE_VAR_DIA_Y])
        if d_x <= 0 and d_y <= 0:
            return None, _ERROR_INVALID_MISSING_DIAMETER
        cx_m = float(vd[PROBE_VAR_CENTER_X])
        cy_m = float(vd[PROBE_VAR_CENTER_Y])
        wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
        if diameters_equal(d_x, d_y, tolerance_mm=tolerance_mm):
            r = d_x / 2.0
            if r <= 0:
                return None, _ERROR_INVALID_MISSING_DIAMETER
            return (
                ProbeScanFeature.new_circle(label, wx, wy, r, coord_sys=CoordSys.WCS),
                None,
            )
        if d_x <= 0 or d_y <= 0:
            return None, _ERROR_INVALID_MISSING_DIAMETER
        return (
            ProbeScanFeature.new_ellipse(
                label, wx, wy, d_x, d_y, coord_sys=CoordSys.WCS
            ),
            None,
        )

    return None, _ERROR_INCOMPLETE_DATA
