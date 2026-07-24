"""
MJPEG-over-HTTP camera source.

The near-universal format for network cameras, including retrofitted ESP32-CAM
modules: the server answers a plain GET with ``multipart/x-mixed-replace`` and
writes each JPEG frame as one part. Parts are split on ``Content-Length`` when one
is sent and on the next boundary marker when not.
"""

from __future__ import annotations

import re
import socket

from carveracontroller.addons.camera.sources.base import READ_TIMEOUT, CameraSource, CameraStreamClosed

CONTENT_TYPE = b"multipart/x-mixed-replace"

_RECV_SIZE = 65536
_BOUNDARY_PATTERN = re.compile(rb"boundary=\"?([^\";\r\n]+)", re.IGNORECASE)
_CONTENT_LENGTH_PATTERN = re.compile(rb"content-length:\s*(\d+)", re.IGNORECASE)


def parse_part(buffer: bytes, boundary: bytes) -> tuple[bytes, int] | None:
    """Return the leading part's JPEG bytes and how much of ``buffer`` to drop.

    Returns None while the part is still incomplete.
    """
    marker = b"--" + boundary
    start = buffer.find(marker)
    if start < 0:
        return None
    headers_start = start + len(marker)
    headers_end = buffer.find(b"\r\n\r\n", headers_start)
    if headers_end < 0:
        return None
    body_start = headers_end + 4
    length_match = _CONTENT_LENGTH_PATTERN.search(buffer[headers_start:headers_end])
    if length_match is None:
        next_start = buffer.find(marker, body_start)
        if next_start < 0:
            return None
        return bytes(buffer[body_start:next_start]).rstrip(b"\r\n"), next_start
    length = int(length_match.group(1))
    if len(buffer) < body_start + length:
        return None
    return bytes(buffer[body_start : body_start + length]), body_start + length


class MjpegHttpSource(CameraSource):
    name = "mjpeg-http"

    def __init__(self, host, port, path, timeout):
        self._socket = socket.create_connection((host, port), timeout=timeout)
        self._buffer = bytearray()
        self._boundary = self._request(host, port, path)
        self._socket.settimeout(READ_TIMEOUT)

    def _request(self, host, port, path):
        """Send the GET and return the multipart boundary the server declared."""
        request = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nAccept: */*\r\nConnection: close\r\n\r\n"
        self._socket.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._socket.recv(_RECV_SIZE)
            if not chunk:
                raise ConnectionError("MJPEG stream closed during response headers")
            response += chunk
        headers, _, trailing = response.partition(b"\r\n\r\n")
        status_line = headers.split(b"\r\n", 1)[0]
        if b" 200 " not in status_line:
            raise ConnectionError(f"MJPEG request failed: {status_line.decode('latin-1', 'replace')}")
        if CONTENT_TYPE not in headers.lower():
            raise ConnectionError("Response is not an MJPEG stream")
        boundary = _BOUNDARY_PATTERN.search(headers)
        if boundary is None:
            raise ConnectionError("MJPEG stream declared no multipart boundary")
        self._buffer += trailing
        return boundary.group(1)

    def next_frame(self):
        parsed = parse_part(self._buffer, self._boundary)
        if parsed is not None:
            jpeg, consumed = parsed
            del self._buffer[:consumed]
            return jpeg
        try:
            chunk = self._socket.recv(_RECV_SIZE)
        except socket.timeout:
            return None
        if not chunk:
            raise CameraStreamClosed
        self._buffer += chunk
        return None

    def close(self):
        try:
            self._socket.close()
        except OSError:
            pass
