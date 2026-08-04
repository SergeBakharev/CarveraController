"""Import CMM Workbench sessions from JSON, CSV, and DXF."""

from __future__ import annotations

import ast
import csv
import io
import logging
import math
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ezdxf.entities import DXFEntity

from .features import payload_referenced_feature_ids
from .io_export import DXF_LAYERS
from .session import (
    CMMWorkbenchFeature,
    CMMWorkbenchSession,
    FeatureKind,
)

logger = logging.getLogger(__name__)

_MAX_CSV_ROWS = 10_000
_CSV_REQUIRED = frozenset({"id", "kind", "label"})
_SNAP_KINDS = frozenset(
    {
        FeatureKind.POINT,
        FeatureKind.CORNER,
        FeatureKind.DERIVED_POINT,
    }
)


@dataclass
class ImportReport:
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0
    imported: int = 0


def load_session_from_path(path: str) -> tuple[CMMWorkbenchSession, ImportReport]:
    with open(path, encoding="utf-8-sig") as fp:
        text = fp.read()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        session = CMMWorkbenchSession.loads(text)
        report = ImportReport(imported=len(session.features))
        _validate_references(session.features, report)
        return session, report
    if ext == ".csv":
        return import_csv(text)
    if ext == ".dxf":
        return import_dxf(text)
    raise ValueError(f"Unsupported file extension {ext!r} (use .json, .csv, or .dxf)")


def import_csv(text: str) -> tuple[CMMWorkbenchSession, ImportReport]:
    report = ImportReport()
    if not text.strip():
        raise ValueError("Empty CSV file")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")
    headers = {h.strip().lower() for h in reader.fieldnames if h}
    if not headers >= _CSV_REQUIRED:
        missing = ", ".join(sorted(_CSV_REQUIRED - headers))
        raise ValueError(f"CSV missing required columns: {missing}")

    def col(row: dict, name: str) -> str:
        for k, v in row.items():
            if k and k.strip().lower() == name:
                return (v or "").strip()
        return ""

    features: list[CMMWorkbenchFeature] = []
    seen_ids: set[str] = set()
    row_count = 0

    for row in reader:
        row_count += 1
        if row_count > _MAX_CSV_ROWS:
            report.warnings.append(f"Stopped after {_MAX_CSV_ROWS} rows")
            break

        kind_raw = col(row, "kind")
        if not kind_raw:
            report.skipped += 1
            continue
        try:
            kind = FeatureKind(kind_raw)
        except ValueError:
            report.warnings.append(f"Skipped row with invalid kind {kind_raw!r}")
            report.skipped += 1
            continue

        feat_id = col(row, "id") or str(uuid.uuid4())
        if feat_id in seen_ids:
            report.warnings.append(f"Duplicate feature id {feat_id!r}; keeping first")
            report.skipped += 1
            continue
        seen_ids.add(feat_id)

        payload: dict = {}
        extra_raw = col(row, "extra")
        if extra_raw:
            try:
                parsed = ast.literal_eval(extra_raw)
                if isinstance(parsed, dict):
                    payload.update(parsed)
                else:
                    report.warnings.append(f"Feature {feat_id}: extra is not a dict; ignored")
            except (SyntaxError, ValueError) as e:
                report.warnings.append(f"Feature {feat_id}: could not parse extra ({e})")

        _merge_csv_geometry(kind, payload, row, col, report)

        features.append(
            CMMWorkbenchFeature(
                id=feat_id,
                kind=kind,
                label=col(row, "label"),
                payload=payload,
            )
        )

    session = CMMWorkbenchSession(features=features)
    report.imported = len(features)
    _validate_references(features, report)
    return session, report


def _merge_csv_geometry(
    kind: FeatureKind,
    payload: dict,
    row: dict,
    col: Callable[[dict, str], str],
    report: ImportReport,
) -> None:
    x_s, y_s, z_s, r_s = col(row, "x"), col(row, "y"), col(row, "z"), col(row, "r")
    dx_s, dy_s = col(row, "diameter_x"), col(row, "diameter_y")
    feat_id = col(row, "id") or "?"

    def _f(s: str, field: str) -> float | None:
        if not s:
            return None
        try:
            return float(s.replace(",", "."))
        except ValueError:
            report.warnings.append(f"Feature {feat_id}: invalid number in {field}: {s!r}")
            return None

    if kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE, FeatureKind.ELLIPSE):
        fx, fy, fz = _f(x_s, "x"), _f(y_s, "y"), _f(z_s, "z")
        if fx is not None:
            payload["cx"] = fx
        if fy is not None:
            payload["cy"] = fy
        if fz is not None:
            payload["z"] = fz
        if kind == FeatureKind.CIRCLE:
            fr = _f(r_s, "r")
            if fr is not None:
                payload["r"] = fr
        elif kind == FeatureKind.ELLIPSE:
            fdx, fdy = _f(dx_s, "diameter_x"), _f(dy_s, "diameter_y")
            if fdx is not None:
                payload["diameter_x"] = fdx
            if fdy is not None:
                payload["diameter_y"] = fdy
        elif kind == FeatureKind.DERIVED_CIRCLE:
            fr = _f(r_s, "r")
            if fr is not None:
                payload["r"] = fr
        return

    fx, fy, fz = _f(x_s, "x"), _f(y_s, "y"), _f(z_s, "z")
    if fx is not None:
        payload["x"] = fx
    if fy is not None:
        payload["y"] = fy
    if fz is not None:
        payload["z"] = fz


def import_dxf(text: str) -> tuple[CMMWorkbenchSession, ImportReport]:
    import ezdxf

    report = ImportReport()
    if not text.strip():
        raise ValueError("Empty DXF file")

    try:
        doc = ezdxf.read(io.StringIO(text))
    except ezdxf.DXFError as e:
        raise ValueError(f"Invalid DXF: {e}") from e

    features: list[CMMWorkbenchFeature] = []
    registry = _PointRegistry(features, report)
    msp = doc.modelspace()
    entities = list(msp)
    by_layer: dict[str, list[DXFEntity]] = {}
    for ent in entities:
        layer = str(ent.dxf.layer) if ent.dxf.hasattr("layer") else "0"
        by_layer.setdefault(layer, []).append(ent)

    probe_layer_set = set(DXF_LAYERS)
    consumed: set[DXFEntity] = set()

    def mark_used(batch: list[DXFEntity]) -> None:
        consumed.update(batch)

    # CMM Workbench layers (/!\ order matters)
    _import_dxf_probed_points(by_layer.get("PROBED_POINTS", []), features, report, consumed)
    _import_dxf_probed_corners(by_layer.get("PROBED_CORNERS", []), features, report, consumed)
    _import_dxf_probed_angles(by_layer.get("PROBED_ANGLES", []), features, report, consumed)
    _import_dxf_probed_centers(by_layer.get("PROBED_CENTERS", []), features, report, registry, consumed)
    _import_dxf_segments(by_layer.get("CONSTRUCTED_SEGMENTS", []), features, report, registry, consumed)
    _import_dxf_polylines(by_layer.get("CONSTRUCTED_POLYLINES", []), features, report, registry, consumed)
    _import_dxf_derived_circles(by_layer.get("CONSTRUCTED_CIRCLES", []), features, report, consumed)
    _import_dxf_derived_points(by_layer.get("CONSTRUCTED_POINTS", []), features, report, registry, consumed)

    # Generic fallback for other layers
    for ent in entities:
        if ent in consumed:
            continue
        layer = str(ent.dxf.layer) if ent.dxf.hasattr("layer") else "0"
        if layer in probe_layer_set:
            continue
        consumed.add(ent)
        dtype = ent.dxftype()
        if dtype == "POINT":
            loc = ent.dxf.location
            registry.snap(
                float(loc.x),
                float(loc.y),
                float(loc.z),
                kind=FeatureKind.POINT,
                prefix="P",
            )
        elif dtype == "CIRCLE":
            center = ent.dxf.center
            r = float(ent.dxf.radius)
            kind = FeatureKind.DERIVED_CIRCLE if "CONSTRUCT" in layer.upper() else FeatureKind.CIRCLE
            _add_circle_feature(
                features,
                report,
                kind,
                float(center.x),
                float(center.y),
                r,
                prefix="C" if kind == FeatureKind.CIRCLE else "DC",
            )
        elif dtype == "ELLIPSE":
            _add_ellipse_from_dxf(ent, features, report, prefix="E")
        elif dtype == "LINE":
            _add_segment_from_line(ent, features, report, registry)
        elif dtype in ("LWPOLYLINE", "POLYLINE"):
            _add_polyline_entity(ent, features, report, registry)
        else:
            report.warnings.append(f"Skipped unsupported entity {dtype} on layer {layer!r}")
            report.skipped += 1

    session = CMMWorkbenchSession(features=features)
    report.imported = len(features)
    return session, report


class _PointRegistry:
    def __init__(self, features: list[CMMWorkbenchFeature], report: ImportReport) -> None:
        self._features = features
        self._report = report
        self._counters: dict[str, int] = {}

    def _next_label(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}{n}"

    def _coords_of(self, feat: CMMWorkbenchFeature) -> tuple[float, float, float] | None:
        p = feat.payload
        if feat.kind == FeatureKind.POINT:
            return float(p["x"]), float(p["y"]), float(p.get("z", 0.0))
        if feat.kind == FeatureKind.CORNER:
            return float(p["x"]), float(p["y"]), 0.0
        if feat.kind == FeatureKind.DERIVED_POINT:
            return float(p["x"]), float(p["y"]), float(p.get("z", 0.0))
        return None

    def snap(
        self,
        x: float,
        y: float,
        z: float = 0.0,
        *,
        kind: FeatureKind = FeatureKind.POINT,
        prefix: str = "P",
    ) -> str:
        for feat in self._features:
            if feat.kind not in _SNAP_KINDS:
                continue
            coords = self._coords_of(feat)
            if coords is None:
                continue
            fx, fy, fz = coords
            if abs(fx - x) <= 1e-4 and abs(fy - y) <= 1e-4 and abs(fz - z) <= 1e-4:
                return feat.id

        label = self._next_label(prefix)
        if kind == FeatureKind.CORNER:
            feat = CMMWorkbenchFeature.new_corner(label, x, y)
        elif kind == FeatureKind.DERIVED_POINT:
            feat = CMMWorkbenchFeature(
                id=str(uuid.uuid4()),
                kind=FeatureKind.DERIVED_POINT,
                label=label,
                payload={"x": x, "y": y, "z": z},
            )
        else:
            feat = CMMWorkbenchFeature.new_point(label, x, y, z)
        self._features.append(feat)
        return feat.id


def _import_dxf_probed_points(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    consumed: set[DXFEntity],
) -> None:
    n = 0
    for ent in entities:
        if ent.dxftype() != "POINT":
            report.warnings.append(f"Skipped non-POINT on PROBED_POINTS: {ent.dxftype()}")
            report.skipped += 1
            continue
        consumed.add(ent)
        loc = ent.dxf.location
        n += 1
        features.append(
            CMMWorkbenchFeature.new_point(
                f"P{n}",
                float(loc.x),
                float(loc.y),
                float(loc.z),
            )
        )


_RE_ANGLE_DXF_TEXT = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:°|\u00b0|deg)\b",
    re.IGNORECASE,
)


def _import_dxf_probed_angles(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    consumed: set[DXFEntity],
) -> None:
    n = 0
    for ent in entities:
        dtype = ent.dxftype()
        if dtype not in ("TEXT", "MTEXT"):
            report.warnings.append(f"Skipped non-text entity on PROBED_ANGLES: {dtype}")
            report.skipped += 1
            continue
        consumed.add(ent)
        if dtype == "TEXT":
            raw = str(ent.dxf.text)
            ins = ent.dxf.insert
        else:
            raw = ent.plain_text() if hasattr(ent, "plain_text") else str(ent.text)
            ins = ent.dxf.insert
        m = _RE_ANGLE_DXF_TEXT.search(raw)
        if not m:
            report.warnings.append(f"Skipped angle label without degrees: {raw!r}")
            report.skipped += 1
            continue
        deg = float(m.group(1))
        n += 1
        features.append(
            CMMWorkbenchFeature.new_angle(
                f"A{n}",
                deg,
                x=float(ins.x),
                y=float(ins.y),
                z=float(getattr(ins, "z", 0.0)),
            )
        )


def _import_dxf_probed_corners(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    consumed: set[DXFEntity],
) -> None:
    n = 0
    for ent in entities:
        if ent.dxftype() != "POINT":
            report.warnings.append(f"Skipped non-POINT on PROBED_CORNERS: {ent.dxftype()}")
            report.skipped += 1
            continue
        consumed.add(ent)
        loc = ent.dxf.location
        n += 1
        features.append(CMMWorkbenchFeature.new_corner(f"K{n}", float(loc.x), float(loc.y)))


def _import_dxf_probed_centers(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    registry: _PointRegistry,
    consumed: set[DXFEntity],
) -> None:
    circles = [e for e in entities if e.dxftype() == "CIRCLE"]
    ellipses = [e for e in entities if e.dxftype() == "ELLIPSE"]
    points = [e for e in entities if e.dxftype() == "POINT"]
    other = [e for e in entities if e.dxftype() not in ("CIRCLE", "ELLIPSE", "POINT")]
    for ent in other:
        report.warnings.append(f"Skipped unsupported entity on PROBED_CENTERS: {ent.dxftype()}")
        report.skipped += 1

    curve_centers: list[tuple[float, float, float]] = []
    n = 0
    for ent in circles:
        consumed.add(ent)
        center = ent.dxf.center
        r = float(ent.dxf.radius)
        cx, cy = float(center.x), float(center.y)
        curve_centers.append((cx, cy, 0.0))
        n += 1
        features.append(CMMWorkbenchFeature.new_circle(f"C{n}", cx, cy, r))

    for ent in ellipses:
        consumed.add(ent)
        parsed = _parse_axis_aligned_dxf_ellipse(ent, report)
        if parsed is None:
            continue
        cx, cy, dx, dy = parsed
        curve_centers.append((cx, cy, 0.0))
        n += 1
        features.append(CMMWorkbenchFeature.new_ellipse(f"E{n}", cx, cy, dx, dy))

    for ent in points:
        consumed.add(ent)
        loc = ent.dxf.location
        x, y, z = float(loc.x), float(loc.y), float(loc.z)
        if any(abs(x - cx) <= 1e-4 and abs(y - cy) <= 1e-4 and abs(z - cz) <= 1e-4 for cx, cy, cz in curve_centers):
            continue
        registry.snap(x, y, z, kind=FeatureKind.POINT, prefix="P")


def _import_dxf_segments(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    registry: _PointRegistry,
    consumed: set[DXFEntity],
) -> None:
    n = 0
    for ent in entities:
        if ent.dxftype() != "LINE":
            report.warnings.append(f"Skipped non-LINE on CONSTRUCTED_SEGMENTS: {ent.dxftype()}")
            report.skipped += 1
            continue
        consumed.add(ent)
        n += 1
        _add_segment_from_line(ent, features, report, registry, label=f"S{n}")


def _add_segment_from_line(
    ent: DXFEntity,
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    registry: _PointRegistry,
    *,
    label: str | None = None,
) -> None:
    start = ent.dxf.start
    end = ent.dxf.end
    x1, y1, z1 = float(start.x), float(start.y), float(start.z)
    x2, y2, z2 = float(end.x), float(end.y), float(end.z)
    if abs(x1 - x2) <= 1e-4 and abs(y1 - y2) <= 1e-4:
        report.warnings.append("Skipped zero-length line")
        report.skipped += 1
        return
    a_id = registry.snap(x1, y1, z1, prefix="P")
    b_id = registry.snap(x2, y2, z2, prefix="P")
    if label is None:
        label = registry._next_label("S")
    features.append(CMMWorkbenchFeature.new_segment(label, a_id, b_id))


def _import_dxf_polylines(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    registry: _PointRegistry,
    consumed: set[DXFEntity],
) -> None:
    n = 0
    for ent in entities:
        dtype = ent.dxftype()
        if dtype not in ("LWPOLYLINE", "POLYLINE"):
            report.warnings.append(f"Skipped non-polyline on CONSTRUCTED_POLYLINES: {dtype}")
            report.skipped += 1
            continue
        consumed.add(ent)
        n += 1
        _add_polyline_entity(ent, features, report, registry, label=f"PL{n}")


def _add_polyline_entity(
    ent: DXFEntity,
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    registry: _PointRegistry,
    *,
    label: str | None = None,
) -> None:
    verts: list[tuple[float, float, float]] = []
    closed = False
    if ent.dxftype() == "LWPOLYLINE":
        closed = bool(ent.closed)
        for x, y, *_ in ent.get_points("xy"):
            verts.append((float(x), float(y), 0.0))
    else:
        closed = ent.is_closed
        for v in ent.vertices:
            loc = v.dxf.location
            verts.append((float(loc.x), float(loc.y), float(loc.z)))

    if len(verts) < 2:
        report.warnings.append("Skipped polyline with fewer than 2 vertices")
        report.skipped += 1
        return

    vertex_ids: list[str] = []
    for x, y, z in verts:
        vertex_ids.append(registry.snap(x, y, z, prefix="P"))

    if label is None:
        label = registry._next_label("PL")
    features.append(CMMWorkbenchFeature.new_polyline(label, vertex_ids, closed=closed))


def _import_dxf_derived_circles(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    consumed: set[DXFEntity],
) -> None:
    n = 0
    for ent in entities:
        if ent.dxftype() != "CIRCLE":
            report.warnings.append(f"Skipped non-CIRCLE on CONSTRUCTED_CIRCLES: {ent.dxftype()}")
            report.skipped += 1
            continue
        consumed.add(ent)
        center = ent.dxf.center
        r = float(ent.dxf.radius)
        n += 1
        features.append(
            CMMWorkbenchFeature(
                id=str(uuid.uuid4()),
                kind=FeatureKind.DERIVED_CIRCLE,
                label=f"DC{n}",
                payload={
                    "cx": float(center.x),
                    "cy": float(center.y),
                    "r": r,
                },
            )
        )


def _import_dxf_derived_points(
    entities: list[DXFEntity],
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    registry: _PointRegistry,
    consumed: set[DXFEntity],
) -> None:
    for ent in entities:
        if ent.dxftype() != "POINT":
            report.warnings.append(f"Skipped non-POINT on CONSTRUCTED_POINTS: {ent.dxftype()}")
            report.skipped += 1
            continue
        consumed.add(ent)
        loc = ent.dxf.location
        registry.snap(
            float(loc.x),
            float(loc.y),
            float(loc.z),
            kind=FeatureKind.DERIVED_POINT,
            prefix="DP",
        )


def _add_circle_feature(
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    kind: FeatureKind,
    cx: float,
    cy: float,
    r: float,
    *,
    prefix: str,
) -> None:
    if r <= 0:
        report.warnings.append(f"Skipped circle with non-positive radius ({r})")
        report.skipped += 1
        return
    n = sum(1 for f in features if f.kind == kind) + 1
    if kind == FeatureKind.DERIVED_CIRCLE:
        features.append(
            CMMWorkbenchFeature(
                id=str(uuid.uuid4()),
                kind=kind,
                label=f"{prefix}{n}",
                payload={"cx": cx, "cy": cy, "r": r},
            )
        )
    else:
        features.append(CMMWorkbenchFeature.new_circle(f"{prefix}{n}", cx, cy, r))


def _parse_axis_aligned_dxf_ellipse(
    ent: DXFEntity,
    report: ImportReport,
) -> tuple[float, float, float, float] | None:
    """Return (cx, cy, diameter_x, diameter_y) for axis-aligned DXF ELLIPSE."""
    center = ent.dxf.center
    cx, cy = float(center.x), float(center.y)
    major = ent.dxf.major_axis
    mx, my = float(major.x), float(major.y)
    major_len = math.hypot(mx, my)
    if major_len < 1e-12:
        report.warnings.append("Skipped ELLIPSE with zero major axis")
        report.skipped += 1
        return None
    ratio = float(ent.dxf.ratio)
    minor_len = major_len * ratio
    if abs(my) <= 1e-9 and abs(mx) > 1e-9:
        dx, dy = 2.0 * major_len, 2.0 * minor_len
    elif abs(mx) <= 1e-9 and abs(my) > 1e-9:
        dx, dy = 2.0 * minor_len, 2.0 * major_len
    else:
        report.warnings.append("Skipped rotated ELLIPSE (only axis-aligned ellipses are supported)")
        report.skipped += 1
        return None
    return cx, cy, dx, dy


def _add_ellipse_from_dxf(
    ent: DXFEntity,
    features: list[CMMWorkbenchFeature],
    report: ImportReport,
    *,
    prefix: str,
) -> None:
    parsed = _parse_axis_aligned_dxf_ellipse(ent, report)
    if parsed is None:
        return
    cx, cy, dx, dy = parsed
    n = sum(1 for f in features if f.kind == FeatureKind.ELLIPSE) + 1
    features.append(CMMWorkbenchFeature.new_ellipse(f"{prefix}{n}", cx, cy, dx, dy))


def _validate_references(features: list[CMMWorkbenchFeature], report: ImportReport) -> None:
    ids = {f.id for f in features}
    for feat in features:
        for ref in payload_referenced_feature_ids(feat.payload):
            if ref not in ids:
                report.warnings.append(f"Feature {feat.id!r} references missing id {ref!r}")
