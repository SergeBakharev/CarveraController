"""Export probe scan sessions to JSON, CSV, and DXF."""

from __future__ import annotations

import csv
import io
import os
import tempfile

from .features import index_by_id, resolve_xy, segment_endpoints
from .session import FeatureKind, ProbeScanSession

DXF_LAYERS = (
    "PROBED_POINTS",
    "PROBED_CENTERS",
    "PROBED_CORNERS",
    "PROBED_ANGLES",
    "CONSTRUCTED_SEGMENTS",
    "CONSTRUCTED_POLYLINES",
    "CONSTRUCTED_CIRCLES",
    "CONSTRUCTED_POINTS",
)

_DXF_ANGLE_TEXT_HEIGHT_MM = 2.0


def export_json(session: ProbeScanSession) -> str:
    return session.dumps()


def export_csv(session: ProbeScanSession) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["id", "kind", "label", "x", "y", "z", "r", "diameter_x", "diameter_y", "extra"]
    )
    for f in session.features:
        p = f.payload
        x = p.get("x", p.get("cx", ""))
        y = p.get("y", p.get("cy", ""))
        z = p.get("z", "")
        r = ""
        d_x = ""
        d_y = ""
        if f.kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE):
            r = p.get("r", "")
        elif f.kind == FeatureKind.ELLIPSE:
            d_x = p.get("diameter_x", "")
            d_y = p.get("diameter_y", "")
        extra_keys = {
            "x",
            "y",
            "z",
            "cx",
            "cy",
            "r",
            "diameter_x",
            "diameter_y",
        }
        extra = {k: v for k, v in p.items() if k not in extra_keys}
        w.writerow(
            [f.id, f.kind.value, f.label, x, y, z, r, d_x, d_y, str(extra)]
        )
    return buf.getvalue()


def export_dxf(session: ProbeScanSession) -> str:
    """Write a layered DXF (R2010) as a string for clipboard or disk."""
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    for lyr in DXF_LAYERS:
        if lyr not in doc.layers:
            doc.layers.new(lyr)

    msp = doc.modelspace()
    feats = session.features
    by_id = index_by_id(feats)

    for f in feats:
        p = f.payload
        if f.kind == FeatureKind.POINT:
            x = float(p.get("x", 0))
            y = float(p.get("y", 0))
            z = float(p.get("z", 0))
            msp.add_point((x, y, z), dxfattribs={"layer": "PROBED_POINTS"})
        elif f.kind == FeatureKind.CIRCLE:
            cx = float(p.get("cx", 0))
            cy = float(p.get("cy", 0))
            r = float(p.get("r", 0))
            msp.add_point((cx, cy, 0.0), dxfattribs={"layer": "PROBED_CENTERS"})
            if r > 0:
                msp.add_circle((cx, cy), r, dxfattribs={"layer": "PROBED_CENTERS"})
        elif f.kind == FeatureKind.ELLIPSE:
            cx = float(p.get("cx", 0))
            cy = float(p.get("cy", 0))
            rx = float(p.get("diameter_x", 0)) / 2.0
            ry = float(p.get("diameter_y", 0)) / 2.0
            msp.add_point((cx, cy, 0.0), dxfattribs={"layer": "PROBED_CENTERS"})
            _add_dxf_ellipse(msp, cx, cy, rx, ry, layer="PROBED_CENTERS")
        elif f.kind == FeatureKind.CORNER:
            msp.add_point(
                (float(p.get("x", 0)), float(p.get("y", 0)), 0.0),
                dxfattribs={"layer": "PROBED_CORNERS"},
            )
        elif f.kind == FeatureKind.ANGLE:
            try:
                ax = float(p["x"])
                ay = float(p["y"])
            except (KeyError, TypeError, ValueError):
                continue
            _add_dxf_angle(msp, ax, ay, float(p.get("degrees", 0.0)))
        elif f.kind == FeatureKind.SEGMENT:
            ends = segment_endpoints(by_id, f)
            if not ends:
                continue
            (x1, y1), (x2, y2) = ends
            msp.add_line(
                (x1, y1, 0.0),
                (x2, y2, 0.0),
                dxfattribs={"layer": "CONSTRUCTED_SEGMENTS"},
            )
        elif f.kind == FeatureKind.POLYLINE:
            verts = p.get("vertex_feature_ids") or []
            if not isinstance(verts, list):
                continue
            coords: list[tuple[float, float]] = []
            for vid in verts:
                wf = by_id.get(str(vid))
                pt = resolve_xy(wf) if wf else None
                if pt:
                    coords.append(pt)
            if len(coords) < 2:
                continue
            closed = bool(p.get("closed"))
            msp.add_lwpolyline(
                coords,
                dxfattribs={"layer": "CONSTRUCTED_POLYLINES"},
                close=closed,
            )
        elif f.kind == FeatureKind.DERIVED_CIRCLE:
            cx = float(p.get("cx", 0))
            cy = float(p.get("cy", 0))
            r = float(p.get("r", 0))
            if r > 0:
                msp.add_circle((cx, cy), r, dxfattribs={"layer": "CONSTRUCTED_CIRCLES"})
        elif f.kind == FeatureKind.DERIVED_POINT:
            msp.add_point(
                (
                    float(p.get("x", 0)),
                    float(p.get("y", 0)),
                    float(p.get("z", 0)),
                ),
                dxfattribs={"layer": "CONSTRUCTED_POINTS"},
            )

    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        doc.saveas(path)
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _add_dxf_ellipse(
    msp,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    *,
    layer: str,
) -> None:
    major_r = max(rx, ry)
    minor_r = min(rx, ry)
    if major_r <= 0:
        return
    ratio = minor_r / major_r
    if rx >= ry:
        major_axis = (major_r, 0.0, 0.0)
    else:
        major_axis = (0.0, major_r, 0.0)
    msp.add_ellipse(
        (cx, cy, 0.0),
        major_axis=major_axis,
        ratio=ratio,
        dxfattribs={"layer": layer},
    )


def _add_dxf_angle(msp, x: float, y: float, degrees: float) -> None:
    from ezdxf.enums import TextEntityAlignment

    ent = msp.add_text(
        f"{degrees:.3f}\u00b0",
        dxfattribs={
            "layer": "PROBED_ANGLES",
            "height": _DXF_ANGLE_TEXT_HEIGHT_MM,
        },
    )
    ent.set_placement((x, y, 0.0), align=TextEntityAlignment.MIDDLE_CENTER)
