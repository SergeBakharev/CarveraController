"""
MJPEG-over-WebSocket camera source.

The client sends a text start message and the server then pushes every frame as a
binary message of raw JPEG bytes. Fragmented messages are reassembled before a
frame is returned, and text frames are ignored.
"""

import socket

from carveracontroller.addons.camera.sources.base import READ_TIMEOUT, CameraSource, CameraStreamClosed
from carveracontroller.addons.camera.websocket import (
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    WebSocketClient,
)

START_MESSAGE = b"start_stream"


class MjpegWebSocketSource(CameraSource):
    name = "mjpeg-websocket"

    def __init__(self, host, port, path, timeout):
        self._client = WebSocketClient(host, port, path, handshake_timeout=timeout, read_timeout=READ_TIMEOUT)
        self._client.send(OP_TEXT, START_MESSAGE)
        self._pending = bytearray()
        self._receiving = False

    def next_frame(self):
        try:
            frame = self._client.read_frame()
        except socket.timeout:
            return None
        if frame.opcode == OP_CLOSE:
            raise CameraStreamClosed
        if frame.opcode == OP_PING:
            self._client.send(OP_PONG, frame.payload)
        elif frame.opcode == OP_BINARY:
            self._pending = bytearray(frame.payload)
            self._receiving = not frame.fin
            if frame.fin:
                return bytes(self._pending)
        elif frame.opcode == OP_CONTINUATION and self._receiving:
            self._pending += frame.payload
            if frame.fin:
                self._receiving = False
                return bytes(self._pending)
        return None

    def close(self):
        self._client.close()
