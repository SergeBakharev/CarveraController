"""Known camera stream endpoints, probed in order to find a machine's camera."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MjpegEndpoint:
    """Where and how to open an MJPEG-over-WebSocket camera stream."""

    port: int
    path: str
    start_message: bytes


MAKERA_WIFI_CAMERA = MjpegEndpoint(port=82, path="/ws_video", start_message=b"start_stream")

CAMERA_ENDPOINTS = (MAKERA_WIFI_CAMERA,)
