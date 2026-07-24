"""
Camera endpoints, probed in order to find a machine's camera.

To support another camera, add a source module under
``carveracontroller.addons.camera.sources`` and register the location it serves
in ``CAMERA_ENDPOINTS``. Keep that list short: every entry that does not answer
costs one connection timeout before the next is tried.
"""

from __future__ import annotations

from dataclasses import dataclass

from carveracontroller.addons.camera.sources.base import CameraSource
from carveracontroller.addons.camera.sources.mjpeg_http import MjpegHttpSource
from carveracontroller.addons.camera.sources.mjpeg_websocket import MjpegWebSocketSource


@dataclass(frozen=True)
class CameraEndpoint:
    """A camera location and the source class that speaks its protocol."""

    source: type[CameraSource]
    port: int
    path: str

    def open(self, host, timeout):
        return self.source(host, self.port, self.path, timeout)


CAMERA_ENDPOINTS = (
    CameraEndpoint(MjpegWebSocketSource, 82, "/ws_video"),
    CameraEndpoint(MjpegHttpSource, 81, "/stream"),
)
