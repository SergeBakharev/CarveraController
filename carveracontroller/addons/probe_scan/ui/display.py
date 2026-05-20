"""Display formatting helpers for probe scan feature lists.

All functions are pure (no Kivy state) and can be called from any context.
"""

from __future__ import annotations

from carveracontroller.translation import tr

from ..core.features import FeatureKind, ProbeScanFeature, resolve_xy, segment_endpoints


def fmt_wcs_manual_field(v: float) -> str:
    """Format a WCS coordinate value for display in a manual input field."""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def payload_wcs_xyz_for_display(
    feat: ProbeScanFeature,
) -> tuple[float, float, float] | None:
    """Extract (x, y, z) from a feature's payload for display purposes."""
    p = feat.payload
    k = feat.kind
    try:
        if k in (FeatureKind.POINT, FeatureKind.CORNER, FeatureKind.DERIVED_POINT):
            return float(p["x"]), float(p["y"]), float(p.get("z", 0.0))
        if k in (FeatureKind.CIRCLE, FeatureKind.ELLIPSE, FeatureKind.DERIVED_CIRCLE):
            return float(p["cx"]), float(p["cy"]), 0.0
    except (KeyError, TypeError, ValueError):
        return None
    return None


def fmt_wcs_xy_detail(
    x: float,
    y: float,
    *,
    feat: ProbeScanFeature | None,
    z_fallback: float = 0.0,
) -> str:
    """Table detail text: includes Z only when the feature stores elevation."""
    if feat is not None and "z" in feat.payload:
        try:
            zv = float(feat.payload["z"])
        except (TypeError, ValueError):
            zv = z_fallback
        return tr._("X=%(x).3f  Y=%(y).3f  Z=%(z).3f") % {
            "x": x,
            "y": y,
            "z": zv,
        }
    return tr._("X=%(x).3f  Y=%(y).3f") % {"x": x, "y": y}


def feature_secondary_line(
    feat: ProbeScanFeature,
    by_id: dict[str, ProbeScanFeature],
) -> str:
    """Build the second display line for a feature list row."""
    p = feat.payload
    k = feat.kind

    if k == FeatureKind.ANGLE:
        deg = float(p.get("degrees", 0.0))
        line = tr._("Measured %(deg).5f °") % {"deg": deg}
        pv = str(p.get("probe_variant") or "").strip()
        return f"{line} · {pv}" if pv else line

    xyz = payload_wcs_xyz_for_display(feat)
    if xyz is not None:
        x_, y_, z_ = xyz
        line = fmt_wcs_xy_detail(x_, y_, feat=feat, z_fallback=z_)
        if k == FeatureKind.CIRCLE:
            try:
                d = 2.0 * float(p.get("r", 0.0))
            except (TypeError, ValueError):
                d = 0.0
            dim = tr._("Ø %(d).3f") % {"d": d}
            return f"{line} · {dim}"
        if k == FeatureKind.ELLIPSE:
            try:
                dx = float(p.get("diameter_x", 0.0))
                dy = float(p.get("diameter_y", 0.0))
            except (TypeError, ValueError):
                dx = dy = 0.0
            dim = tr._("Ø %(dx).3f × %(dy).3f") % {"dx": dx, "dy": dy}
            return f"{line} · {dim}"
        if k == FeatureKind.DERIVED_CIRCLE:
            try:
                r = float(p.get("r", 0.0))
            except (TypeError, ValueError):
                r = 0.0
            rad = tr._("R %(r).3f") % {"r": r}
            return f"{line} · {rad}"
        return line

    if k == FeatureKind.SEGMENT:
        ends = segment_endpoints(by_id, feat)
        if not ends:
            return ""
        pa, pb = ends
        wa = by_id.get(str(p.get("a_id", "")))
        wb = by_id.get(str(p.get("b_id", "")))
        za = zb = 0.0
        if wa:
            ta = payload_wcs_xyz_for_display(wa)
            if ta:
                za = ta[2]
        if wb:
            tb = payload_wcs_xyz_for_display(wb)
            if tb:
                zb = tb[2]
        x1, y1 = pa
        x2, y2 = pb
        sa = fmt_wcs_xy_detail(x1, y1, feat=wa, z_fallback=za)
        sb = fmt_wcs_xy_detail(x2, y2, feat=wb, z_fallback=zb)
        return tr._("A %(sa)s  →  B %(sb)s") % {"sa": sa, "sb": sb}

    if k == FeatureKind.POLYLINE:
        verts = p.get("vertex_feature_ids") or []
        if not isinstance(verts, list) or len(verts) < 2:
            return ""
        vert_rows: list[tuple[ProbeScanFeature | None, float, float, float]] = []
        for vid in verts:
            wf = by_id.get(str(vid))
            if wf is None:
                return ""
            xyzv = payload_wcs_xyz_for_display(wf)
            if xyzv is not None:
                vert_rows.append((wf, xyzv[0], xyzv[1], xyzv[2]))
                continue
            xy = resolve_xy(wf)
            if xy is None:
                return ""
            vert_rows.append((wf, float(xy[0]), float(xy[1]), 0.0))
        n = len(vert_rows)
        if n <= 4:
            parts = [
                tr._("%(vi)d: %(det)s")
                % {
                    "vi": i + 1,
                    "det": fmt_wcs_xy_detail(vx, vy, feat=wf, z_fallback=vz),
                }
                for i, (wf, vx, vy, vz) in enumerate(vert_rows)
            ]
            return "; ".join(parts)
        wf0, x0, y0, z0 = vert_rows[0]
        wfk, xk, yk, zk = vert_rows[-1]
        s0 = fmt_wcs_xy_detail(x0, y0, feat=wf0, z_fallback=z0)
        sk = fmt_wcs_xy_detail(xk, yk, feat=wfk, z_fallback=zk)
        return tr._("%(num)d verts: %(s0)s  …  %(sk)s") % {
            "num": n,
            "s0": s0,
            "sk": sk,
        }

    return ""
