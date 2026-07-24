"""
Minimal RFC 6455 WebSocket client: frame encode/decode plus a blocking socket.

Client side only, plain ``ws://`` (no TLS) and no protocol extensions, which is
all the controller needs. Hand-rolled rather than pulling in a ``websockets``
dependency that would have to be threaded through the desktop, Android and iOS
builds.
"""

from __future__ import annotations

import base64
import os
import socket
import struct
from dataclasses import dataclass

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

DEFAULT_HANDSHAKE_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 1.0

_RECV_SIZE = 65536

_LENGTH_16BIT = 126
_LENGTH_64BIT = 127
_FIN_BIT = 0x80
_MASK_BIT = 0x80
_OPCODE_MASK = 0x0F
_LENGTH_MASK = 0x7F


@dataclass
class Frame:
    fin: bool
    opcode: int
    payload: bytes


def _apply_mask(payload: bytes, mask: bytes) -> bytes:
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


def build_frame(opcode: int, payload: bytes = b"", mask: bytes | None = None) -> bytes:
    """Return one client frame; client frames are always masked (RFC 6455 5.3)."""
    if mask is None:
        mask = os.urandom(4)
    header = bytearray([_FIN_BIT | opcode])
    length = len(payload)
    if length < _LENGTH_16BIT:
        header.append(_MASK_BIT | length)
    elif length < 65536:
        header.append(_MASK_BIT | _LENGTH_16BIT)
        header += struct.pack(">H", length)
    else:
        header.append(_MASK_BIT | _LENGTH_64BIT)
        header += struct.pack(">Q", length)
    return bytes(header) + mask + _apply_mask(payload, mask)


def parse_frame(buffer: bytes) -> tuple[Frame, int] | None:
    """Return the leading frame and its byte length, or None while incomplete."""
    if len(buffer) < 2:
        return None
    fin = bool(buffer[0] & _FIN_BIT)
    opcode = buffer[0] & _OPCODE_MASK
    masked = bool(buffer[1] & _MASK_BIT)
    length = buffer[1] & _LENGTH_MASK
    offset = 2
    if length == _LENGTH_16BIT:
        if len(buffer) < offset + 2:
            return None
        length = struct.unpack_from(">H", buffer, offset)[0]
        offset += 2
    elif length == _LENGTH_64BIT:
        if len(buffer) < offset + 8:
            return None
        length = struct.unpack_from(">Q", buffer, offset)[0]
        offset += 8
    mask = b""
    if masked:
        if len(buffer) < offset + 4:
            return None
        mask = buffer[offset : offset + 4]
        offset += 4
    if len(buffer) < offset + length:
        return None
    payload = bytes(buffer[offset : offset + length])
    if masked:
        payload = _apply_mask(payload, mask)
    return Frame(fin, opcode, payload), offset + length


class WebSocketClient:
    """Blocking client: masked sends, framed reads, ping/pong and close."""

    def __init__(
        self,
        host: str,
        port: int,
        path: str,
        handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        self._socket = socket.create_connection((host, port), timeout=handshake_timeout)
        self._buffer = bytearray(self._handshake(host, port, path))
        self._socket.settimeout(read_timeout)

    def _handshake(self, host: str, port: int, path: str) -> bytes:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._socket.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._socket.recv(_RECV_SIZE)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed by peer")
            response += chunk
        header, _, trailing = response.partition(b"\r\n\r\n")
        status_line = header.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise ConnectionError(f"WebSocket handshake failed: {status_line.decode('latin-1', 'replace')}")
        return trailing

    def read_frame(self) -> Frame:
        """Return the next frame, raising ``socket.timeout`` when idle."""
        while True:
            parsed = parse_frame(self._buffer)
            if parsed is not None:
                frame, consumed = parsed
                del self._buffer[:consumed]
                return frame
            chunk = self._socket.recv(_RECV_SIZE)
            if not chunk:
                raise ConnectionError("WebSocket closed by peer")
            self._buffer += chunk

    def send(self, opcode: int, payload: bytes = b"") -> None:
        self._socket.sendall(build_frame(opcode, payload))

    def close(self) -> None:
        try:
            self.send(OP_CLOSE)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass
