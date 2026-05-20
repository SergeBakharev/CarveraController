"""Resolve feature coordinates and dependency IDs for constructions and DXF."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Literal

from .construction_geom import (
    circle_circle_intersections_2d,
    circle_line_intersections_2d,
    ellipse_ellipse_intersections_2d,
    ellipse_line_intersections_2d,
    midpoint_2d,
    tangent_circle_to_circle_external_2d,
    tangent_ellipse_to_ellipse_external_2d,
    tangent_point_to_circle_2d,
    tangent_point_to_ellipse_2d,
)
from .coordinate_transform import mcs_xyz_to_wcs_xyz
from .gcode_m118 import PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y, PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y
from .session import CoordSys, FeatureKind, ProbeScanFeature

_ERROR_INCOMPLETE_DATA = "Probe returned incomplete data."
_ERROR_INVALID_MISSING_DIAMETER = "Invalid or missing diameter in probe result."
_ERROR_PRESET_MISMATCH = "Probe result does not match selected probing option."

DEFAULT_CIRCLE_CLASSIFY_TOLERANCE_MM = 0.02

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


def _normalized_var_keys(var_keys: list[str]) -> set[str]:
    return {str(k).strip() for k in var_keys if str(k).strip()}


def _probe_axis_segment_bundle(
    segment_label: str,
    endpoint_a_label: str,
    endpoint_b_label: str,
    center_label: str,
    cx_m: float,
    cy_m: float,
    diameter: float,
    axis: Literal["x", "y"],
    *,
    include_center: bool = True,
    source: str,
) -> list[ProbeScanFeature]:
    """Horizontal (axis x) or vertical (axis y) chord: endpoints, segment, optional center."""
    half = float(diameter) / 2.0
    if axis == "x":
        x1_m, y1_m = cx_m - half, cy_m
        x2_m, y2_m = cx_m + half, cy_m
    else:
        x1_m, y1_m = cx_m, cy_m - half
        x2_m, y2_m = cx_m, cy_m + half
    wx1, wy1, _ = mcs_xyz_to_wcs_xyz(x1_m, y1_m, 0.0)
    wx2, wy2, _ = mcs_xyz_to_wcs_xyz(x2_m, y2_m, 0.0)
    pa = ProbeScanFeature.new_point(
        endpoint_a_label,
        wx1,
        wy1,
        0.0,
        source=source,
        coord_sys=CoordSys.WCS,
    )
    pb = ProbeScanFeature.new_point(
        endpoint_b_label,
        wx2,
        wy2,
        0.0,
        source=source,
        coord_sys=CoordSys.WCS,
    )
    seg = ProbeScanFeature.new_segment(segment_label, pa.id, pb.id)
    out: list[ProbeScanFeature] = [pa, pb, seg]
    if include_center:
        mx_w, my_w = midpoint_2d(wx1, wy1, wx2, wy2)
        out.append(
            ProbeScanFeature.new_derived_point(center_label, pa.id, pb.id, mx_w, my_w)
        )
    return out


def _probe_rect_cross_features(
    h_segment_label: str,
    h_endpoint_a_label: str,
    h_endpoint_b_label: str,
    v_segment_label: str,
    v_endpoint_a_label: str,
    v_endpoint_b_label: str,
    center_label: str,
    cx_m: float,
    cy_m: float,
    diameter_x: float,
    diameter_y: float,
    *,
    source: str,
) -> list[ProbeScanFeature]:
    """Two orthogonal chords (horizontal + vertical) and one shared center point."""
    h_bundle = _probe_axis_segment_bundle(
        h_segment_label,
        h_endpoint_a_label,
        h_endpoint_b_label,
        center_label,
        cx_m,
        cy_m,
        diameter_x,
        "x",
        include_center=False,
        source=source,
    )
    v_bundle = _probe_axis_segment_bundle(
        v_segment_label,
        v_endpoint_a_label,
        v_endpoint_b_label,
        center_label,
        cx_m,
        cy_m,
        diameter_y,
        "y",
        include_center=False,
        source=source,
    )
    pa, pb = h_bundle[0], h_bundle[1]
    wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
    center = ProbeScanFeature.new_derived_point(center_label, pa.id, pb.id, wx, wy)
    return h_bundle + v_bundle + [center]


def _features_circle_or_ellipse(
    label: str,
    cx_m: float,
    cy_m: float,
    diameter_x: float,
    diameter_y: float,
    *,
    tolerance_mm: float,
) -> tuple[list[ProbeScanFeature], str | None]:
    wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
    if diameters_equal(diameter_x, diameter_y, tolerance_mm=tolerance_mm):
        r = diameter_x / 2.0
        if r <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        return (
            [ProbeScanFeature.new_circle(label, wx, wy, r, coord_sys=CoordSys.WCS)],
            None,
        )
    if diameter_x <= 0 or diameter_y <= 0:
        return [], _ERROR_INVALID_MISSING_DIAMETER
    return (
        [
            ProbeScanFeature.new_ellipse(
                label, wx, wy, diameter_x, diameter_y, coord_sys=CoordSys.WCS
            )
        ],
        None,
    )


def features_from_m461_m462(
    vd: dict[str, float],
    var_keys: list[str],
    *,
    preset: str,
    mx: float,
    my: float,
    segment_label: str,
    endpoint_a_label: str,
    endpoint_b_label: str,
    center_label: str,
    h_segment_label: str,
    h_endpoint_a_label: str,
    h_endpoint_b_label: str,
    v_segment_label: str,
    v_endpoint_a_label: str,
    v_endpoint_b_label: str,
    curve_label: str,
    source: str,
    tolerance_mm: float | None = None,
) -> tuple[list[ProbeScanFeature], str | None]:
    """
    Build probe-scan features from M461/M462 variables and UI preset.

    Returns (features, error_message). On success error_message is None.
    """
    keys = _normalized_var_keys(var_keys)

    if preset == "CenterX":
        if keys != {PROBE_VAR_DIA_X, PROBE_VAR_CENTER_X}:
            return [], _ERROR_PRESET_MISMATCH
        if PROBE_VAR_DIA_X not in vd or PROBE_VAR_CENTER_X not in vd:
            return [], _ERROR_INCOMPLETE_DATA
        d_x = float(vd[PROBE_VAR_DIA_X])
        if d_x <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        cx_m = float(vd[PROBE_VAR_CENTER_X])
        cy_m = float(vd[PROBE_VAR_CENTER_Y]) if PROBE_VAR_CENTER_Y in vd else float(my)
        return (
            _probe_axis_segment_bundle(
                segment_label,
                endpoint_a_label,
                endpoint_b_label,
                center_label,
                cx_m,
                cy_m,
                d_x,
                "x",
                source=source,
            ),
            None,
        )

    if preset == "CenterY":
        if keys != {PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_Y}:
            return [], _ERROR_PRESET_MISMATCH
        if PROBE_VAR_DIA_Y not in vd or PROBE_VAR_CENTER_Y not in vd:
            return [], _ERROR_INCOMPLETE_DATA
        d_y = float(vd[PROBE_VAR_DIA_Y])
        if d_y <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        cy_m = float(vd[PROBE_VAR_CENTER_Y])
        cx_m = float(vd[PROBE_VAR_CENTER_X]) if PROBE_VAR_CENTER_X in vd else float(mx)
        return (
            _probe_axis_segment_bundle(
                segment_label,
                endpoint_a_label,
                endpoint_b_label,
                center_label,
                cx_m,
                cy_m,
                d_y,
                "y",
                source=source,
            ),
            None,
        )

    if preset in ("CenterBore", "CenterBoss", "CenterPocket", "CenterBlock"):
        required_keys = {
            PROBE_VAR_DIA_X,
            PROBE_VAR_DIA_Y,
            PROBE_VAR_CENTER_X,
            PROBE_VAR_CENTER_Y,
        }
        if keys != required_keys:
            return [], _ERROR_PRESET_MISMATCH
        if not all(k in vd for k in required_keys):
            return [], _ERROR_INCOMPLETE_DATA
        d_x = float(vd[PROBE_VAR_DIA_X])
        d_y = float(vd[PROBE_VAR_DIA_Y])
        if d_x <= 0 and d_y <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        cx_m = float(vd[PROBE_VAR_CENTER_X])
        cy_m = float(vd[PROBE_VAR_CENTER_Y])

        if preset in ("CenterPocket", "CenterBlock"):
            if d_x <= 0 or d_y <= 0:
                return [], _ERROR_INVALID_MISSING_DIAMETER
            return (
                _probe_rect_cross_features(
                    h_segment_label,
                    h_endpoint_a_label,
                    h_endpoint_b_label,
                    v_segment_label,
                    v_endpoint_a_label,
                    v_endpoint_b_label,
                    center_label,
                    cx_m,
                    cy_m,
                    d_x,
                    d_y,
                    source=source,
                ),
                None,
            )

        classify_tol = (
            tolerance_mm
            if tolerance_mm is not None
            else DEFAULT_CIRCLE_CLASSIFY_TOLERANCE_MM
        )
        return _features_circle_or_ellipse(
            curve_label,
            cx_m,
            cy_m,
            d_x,
            d_y,
            tolerance_mm=classify_tol,
        )

    return [], _ERROR_PRESET_MISMATCH
