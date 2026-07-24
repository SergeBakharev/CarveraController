"""
Live camera stream over MJPEG-over-WebSocket.

A machine's network module serves the stream at the port and path given by its
endpoint: the client sends a text start message and the server then pushes every
camera frame as a binary WebSocket message of raw JPEG bytes. The stream needs a
network connection because it does not exist on the serial link, and it carries
no camera parameter controls, so it is view-only.

Any machine answering a handshake on a known endpoint is treated as having a
camera, so no model detection is involved.

Frames are read on a worker thread; callbacks are dispatched on the Kivy main
thread.
"""

import logging
import socket
import threading

from kivy.clock import Clock

from carveracontroller.addons.camera.endpoints import CAMERA_ENDPOINTS
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

PROBE_TIMEOUT = 1.5

logger = logging.getLogger(__name__)


def find_camera(host, endpoints=CAMERA_ENDPOINTS, timeout=PROBE_TIMEOUT):
    """Return the first endpoint that completes a handshake with ``host``, else None.

    Blocks for up to ``timeout`` per endpoint, so call it off the main thread.
    """
    for endpoint in endpoints:
        try:
            client = WebSocketClient(host, endpoint.port, endpoint.path, handshake_timeout=timeout)
        except OSError as exc:
            logger.info("No camera at ws://%s:%d%s (%s)", host, endpoint.port, endpoint.path, exc)
            continue
        client.close()
        return endpoint
    return None


class CameraStream:
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

    def is_streaming(self):
        return self._streaming

    def start(self, host, endpoint):
        if self._streaming:
            return
        self._session += 1
        self._streaming = True
        self._notify(self._on_streaming, True)
        threading.Thread(target=self._read_frames, args=(host, endpoint, self._session), daemon=True).start()

    def stop(self):
        """Invalidate the running worker's session, then close its socket."""
        if not self._streaming:
            return
        self._session += 1
        self._streaming = False
        client, self._client = self._client, None
        if client is not None:
            client.close()
        self._notify(self._on_streaming, False)

    def _read_frames(self, host, endpoint, session):
        """Reassemble JPEG messages until stopped or superseded by a newer session.

        The socket is only ever reached through the local ``client``, so a newer
        session replacing ``self._client`` can neither be read nor torn down
        here. Text frames (status chatter) are ignored by this view-only stream.
        """
        client = None
        pending = bytearray()
        receiving = False
        try:
            client = WebSocketClient(host, endpoint.port, endpoint.path)
            self._client = client
            client.send(OP_TEXT, endpoint.start_message)
            logger.info("Camera stream connected to ws://%s:%d%s", host, endpoint.port, endpoint.path)
            while self._streaming and self._session == session:
                try:
                    frame = client.read_frame()
                except socket.timeout:
                    continue
                if frame.opcode == OP_CLOSE:
                    break
                if frame.opcode == OP_PING:
                    client.send(OP_PONG, frame.payload)
                elif frame.opcode == OP_BINARY:
                    pending = bytearray(frame.payload)
                    receiving = not frame.fin
                    if frame.fin:
                        self._notify(self._on_frame, bytes(pending))
                elif frame.opcode == OP_CONTINUATION and receiving:
                    pending += frame.payload
                    if frame.fin:
                        receiving = False
                        self._notify(self._on_frame, bytes(pending))
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

    def _notify(self, callback, value):
        Clock.schedule_once(lambda _dt: callback(value), 0)
