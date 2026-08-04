"""Legacy Smoothieware newline-delimited text protocol."""

from __future__ import annotations

from .base import CommunicationProtocol
from .messages import MessageKind, ParsedMessage

EOT = b"\x04"
CAN = b"\x16"


class SmoothieProtocol(CommunicationProtocol):
    name = "smoothie"
    uses_framed_transfer = False

    def __init__(self) -> None:
        super().__init__()
        self._line = bytearray()

    def encode_command(self, data: bytes) -> bytes:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        text = bytes(data)
        if not text.endswith(b"\n"):
            text += b"\n"
        return text

    def encode_realtime(self, char: int) -> bytes:
        return bytes([char & 0xFF])

    def encode_file_command(self, data: bytes) -> bytes:
        return self.encode_command(data)

    def feed(self, data: bytes) -> list[ParsedMessage]:
        messages: list[ParsedMessage] = []
        for byte in data:
            c = bytes([byte])
            if c in (EOT, CAN):
                if self._line:
                    messages.append(ParsedMessage(MessageKind.LOAD_CHUNK, self._line.decode(errors="ignore")))
                    self._line.clear()
                messages.append(ParsedMessage(MessageKind.LOAD_EOF if c == EOT else MessageKind.LOAD_ERROR))
            elif c == b"\n":
                line = self._line.decode(errors="ignore")
                self._line.clear()
                messages.append(ParsedMessage(MessageKind.LINE, line))
            else:
                self._line.extend(c)
        return messages

    def reset(self) -> None:
        self._line.clear()
        self.ready = False
