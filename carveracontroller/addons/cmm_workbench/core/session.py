"""Session feature model for CMM Workbench."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


SESSION_FORMAT_VERSION = 1


class FeatureKind(str, Enum):
    POINT = "point"
    CIRCLE = "circle"
    ELLIPSE = "ellipse"
    CORNER = "corner"
    ANGLE = "angle"
    SEGMENT = "segment"
    POLYLINE = "polyline"
    DERIVED_CIRCLE = "derived_circle"
    DERIVED_POINT = "derived_point"


@dataclass
class CMMWorkbenchFeature:
    """One measured or constructed feature."""

    id: str
    kind: FeatureKind
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_ts: float = field(default_factory=lambda: time.time())
    sketch_visible: bool = True

    @staticmethod
    def new_point(
        label: str,
        x: float,
        y: float,
        z: float,
        *,
        source: str = "wcs",
    ) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.POINT,
            label=label,
            payload={
                "x": x,
                "y": y,
                "z": z,
                "source": source,
            },
        )

    @staticmethod
    def new_circle(
        label: str,
        cx: float,
        cy: float,
        r: float,
    ) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.CIRCLE,
            label=label,
            payload={
                "cx": cx,
                "cy": cy,
                "r": float(r),
            },
        )

    @staticmethod
    def new_ellipse(
        label: str,
        cx: float,
        cy: float,
        diameter_x: float,
        diameter_y: float,
    ) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.ELLIPSE,
            label=label,
            payload={
                "cx": cx,
                "cy": cy,
                "diameter_x": float(diameter_x),
                "diameter_y": float(diameter_y),
            },
        )

    @staticmethod
    def new_corner(
        label: str,
        x: float,
        y: float,
    ) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.CORNER,
            label=label,
            payload={"x": x, "y": y},
        )

    @staticmethod
    def new_angle(
        label: str,
        degrees: float,
        *,
        probe_variant: str = "",
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> CMMWorkbenchFeature:
        """``degrees`` from M465 probe result (``PROBE_VAR_ANGLE``, firmware #153)."""
        payload: dict[str, Any] = {"degrees": float(degrees)}
        if probe_variant:
            payload["probe_variant"] = str(probe_variant)
        if x is not None and y is not None:
            payload["x"] = float(x)
            payload["y"] = float(y)
            if z is not None:
                payload["z"] = float(z)
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.ANGLE,
            label=label,
            payload=payload,
        )

    @staticmethod
    def new_segment(label: str, a_id: str, b_id: str) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.SEGMENT,
            label=label,
            payload={"a_id": str(a_id), "b_id": str(b_id)},
        )

    @staticmethod
    def new_polyline(
        label: str,
        vertex_feature_ids: list[str],
        *,
        closed: bool = False,
    ) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.POLYLINE,
            label=label,
            payload={
                "vertex_feature_ids": [str(v) for v in vertex_feature_ids],
                "closed": closed,
            },
        )

    @staticmethod
    def new_derived_circle(
        label: str,
        source_ids: tuple[str, str, str],
        cx: float,
        cy: float,
        r: float,
    ) -> CMMWorkbenchFeature:
        a, b, c = source_ids
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.DERIVED_CIRCLE,
            label=label,
            payload={
                "source_ids": [a, b, c],
                "cx": cx,
                "cy": cy,
                "r": r,
            },
        )

    @staticmethod
    def new_derived_point(
        label: str,
        segment_a_id: str,
        segment_b_id: str,
        x: float,
        y: float,
    ) -> CMMWorkbenchFeature:
        return CMMWorkbenchFeature(
            id=str(uuid.uuid4()),
            kind=FeatureKind.DERIVED_POINT,
            label=label,
            payload={
                "segment_a_id": str(segment_a_id),
                "segment_b_id": str(segment_b_id),
                "x": x,
                "y": y,
                "z": 0.0,
            },
        )


@dataclass
class CMMWorkbenchSession:
    """Full scan session for save/load and export."""

    version: int = SESSION_FORMAT_VERSION
    unit_mm: bool = True
    features: list[CMMWorkbenchFeature] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        return {
            "version": self.version,
            "unit_mm": self.unit_mm,
            "features": [
                {
                    "id": f.id,
                    "kind": f.kind.value,
                    "label": f.label,
                    "payload": f.payload,
                    "created_ts": f.created_ts,
                    "sketch_visible": f.sketch_visible,
                }
                for f in self.features
            ],
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> CMMWorkbenchSession:
        feats: list[CMMWorkbenchFeature] = []
        for row in data.get("features", []):
            k = row.get("kind")
            if isinstance(k, FeatureKind):
                kind_enum = k
            else:
                try:
                    kind_enum = FeatureKind(str(k))
                except ValueError:
                    logger.warning(
                        "CMM Workbench session: skip feature with invalid kind %r",
                        k,
                    )
                    continue
            feat = CMMWorkbenchFeature(
                id=row.get("id", str(uuid.uuid4())),
                kind=kind_enum,
                label=row.get("label", ""),
                payload=dict(row.get("payload", {})),
                created_ts=float(row.get("created_ts", time.time())),
                sketch_visible=bool(row.get("sketch_visible", True)),
            )
            feats.append(feat)
        return cls(
            version=SESSION_FORMAT_VERSION,
            unit_mm=bool(data.get("unit_mm", True)),
            features=feats,
        )

    def dumps(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)

    @classmethod
    def loads(cls, s: str) -> CMMWorkbenchSession:
        return cls.from_json_dict(json.loads(s))
