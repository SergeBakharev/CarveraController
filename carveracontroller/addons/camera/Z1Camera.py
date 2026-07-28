"""
Live camera on the Makera Z1.

The camera is served by the Z1's ESP32 WiFi module rather than the motion
firmware: a WebSocket on port 82 that starts pushing frames once the client
sends ``start_stream``, one whole JPEG per binary message. The stream is fixed
at 640x480 by that firmware and exposes no sensor controls, which is why
``CameraView`` grades frames on the host instead.

Frames are read on a worker thread; callbacks are dispatched on the Kivy main
thread.
"""

import json
import logging
import socket
import threading
import urllib.request

from kivy.clock import Clock

from carveracontroller.addons.camera.websocket import (
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    WebSocketClient,
)
from carveracontroller.translation import tr

CAMERA_PORT = 82
CAMERA_PATH = "/ws_video"
START_MESSAGE = b"start_stream"

# Resolution is the one camera setting the machine exposes, and it lives on the
# web UI's port rather than the streaming one. Probing every plausible route
# found no others: exposure, gain and white balance are not reachable, which is
# why CameraView grades frames on the host.
CONTROL_PORT = 80
RESOLUTION_PATH = "/api/camera/resolution"

CONNECT_TIMEOUT = 5.0
PROBE_TIMEOUT = 1.5
CONTROL_TIMEOUT = 5.0
# Reads are sliced so a stop request is not left hanging between frames.
READ_TIMEOUT = 1.0

# Espressif framesize_t values, each measured against a Z1. Frame rate falls off
# as they climb -- 640x480 runs at about 20fps and 1600x1200 at about 10 -- so
# the smallest is the default. Out-of-range values are answered with 200 and
# then ignored by the firmware, so only offer ones known to work.
RESOLUTIONS = (
    (10, (640, 480)),
    (11, (800, 600)),
    (12, (1024, 768)),
    (13, (1280, 720)),
    (14, (1280, 1024)),
    (15, (1600, 1200)),
)
DEFAULT_RESOLUTION = RESOLUTIONS[0][0]
RESOLUTION_LABELS = {value: f"{width}x{height}" for value, (width, height) in RESOLUTIONS}
RESOLUTION_VALUES = {label: value for value, label in RESOLUTION_LABELS.items()}
RESOLUTION_BY_SIZE = {size: value for value, size in RESOLUTIONS}
RESOLUTION_CHOICES = tuple(RESOLUTION_LABELS[value] for value, _size in RESOLUTIONS)

logger = logging.getLogger(__name__)


class CameraStreamClosed(Exception):
    """The camera ended the stream in an orderly way."""


def has_camera(host, timeout=PROBE_TIMEOUT):
    """Return whether a camera answers on ``host``.

    Blocks for up to ``timeout``, so call it off the main thread.
    """
    try:
        client = WebSocketClient(host, CAMERA_PORT, CAMERA_PATH, handshake_timeout=timeout)
    except OSError as exc:
        logger.info("No camera at %s:%d%s (%s)", host, CAMERA_PORT, CAMERA_PATH, exc)
        return False
    client.close()
    return True


def set_resolution(host, value):
    """Switch the camera's resolution, returning whether it was accepted.

    Blocks on the network, so call it off the main thread. A running stream keeps
    going and starts sending the new size within a frame or two, so there is
    nothing to reconnect.
    """
    request = urllib.request.Request(
        f"http://{host}:{CONTROL_PORT}{RESOLUTION_PATH}",
        data=json.dumps({"resolution": value}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=CONTROL_TIMEOUT) as response:
            accepted = response.status == 200
    except OSError as exc:
        logger.error("Camera resolution %s rejected: %s", RESOLUTION_LABELS.get(value, value), exc)
        return False
    logger.info("Camera resolution set to %s", RESOLUTION_LABELS.get(value, value))
    return accepted


class Z1Camera:
    """Owns the reader thread for one camera session.

    ``on_frame`` receives complete JPEG bytes, ``on_streaming`` the current
    streaming state and ``on_error`` a user-facing message.
    """

    def __init__(self, on_frame, on_streaming, on_error):
        self._on_frame = on_frame
        self._on_streaming = on_streaming
        self._on_error = on_error
        self._client = None
        self._streaming = False
        self._session = 0
        self._latest_frame = None
        self._frame_update = None

    def is_streaming(self):
        return self._streaming

    def start(self, host):
        if self._streaming:
            return
        self._session += 1
        self._streaming = True
        self._notify(self._on_streaming, True)
        threading.Thread(target=self._read_frames, args=(host, self._session), daemon=True).start()

    def stop(self):
        """Invalidate the running worker's session, then close its connection."""
        if not self._streaming:
            return
        self._session += 1
        self._streaming = False
        client, self._client = self._client, None
        if client is not None:
            client.close()
        self._notify(self._on_streaming, False)

    def _read_frames(self, host, session):
        """Forward frames until stopped, closed, or superseded by a newer session.

        Only the local ``client`` is used, so a newer session replacing
        ``self._client`` can neither be read nor torn down here.
        """
        client = None
        try:
            client = WebSocketClient(
                host, CAMERA_PORT, CAMERA_PATH, handshake_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT
            )
            self._client = client
            client.send(OP_TEXT, START_MESSAGE)
            logger.info("Camera stream connected: %s:%d%s", host, CAMERA_PORT, CAMERA_PATH)
            pending = bytearray()
            while self._streaming and self._session == session:
                try:
                    frame = client.read_frame()
                except socket.timeout:
                    continue
                if frame.opcode == OP_CLOSE:
                    raise CameraStreamClosed
                if frame.opcode == OP_PING:
                    client.send(OP_PONG, frame.payload)
                    continue
                if frame.opcode == OP_BINARY:
                    pending = bytearray(frame.payload)
                elif frame.opcode == OP_CONTINUATION and pending:
                    pending += frame.payload
                else:
                    # Text messages, and continuations of something we skipped.
                    continue
                if frame.fin:
                    self._show_frame(bytes(pending))
                    pending = bytearray()
        except CameraStreamClosed:
            logger.info("Camera stream closed by the machine")
        except OSError as exc:
            if self._streaming and self._session == session:
                logger.error("Camera stream failed: %s", exc)
                self._notify(self._on_error, tr._("Camera stream error: {}").format(exc))
        finally:
            if client is not None:
                client.close()
            if self._session == session:
                self._client = None
                self._streaming = False
                self._notify(self._on_streaming, False)

    def _show_frame(self, jpeg):
        """Hand the newest frame to the UI, replacing any not drawn yet.

        Decoding happens on the main thread, so a host that cannot keep up with
        the camera has to drop frames instead of queueing them: only one update
        is ever scheduled, and it always draws the latest frame.
        """
        self._latest_frame = jpeg
        if self._frame_update is None:
            self._frame_update = Clock.schedule_once(self._draw_latest_frame, 0)

    def _draw_latest_frame(self, _dt):
        self._frame_update = None
        jpeg, self._latest_frame = self._latest_frame, None
        if jpeg is not None:
            self._on_frame(jpeg)

    def _notify(self, callback, value):
        Clock.schedule_once(lambda _dt: callback(value), 0)
