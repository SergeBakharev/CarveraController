"""Tests for WIFIStream socket write semantics."""

from carveracontroller.WIFIStream import WIFIStream
from carveracontroller.XMODEM import XMODEM


class DeterministicShortWriteSocket:
    """Socket double that accepts only a prefix from each ``send`` call."""

    def __init__(self, short_write_size):
        self.short_write_size = short_write_size
        self.send_calls = 0
        self.sendall_calls = 0
        self.wire = bytearray()

    def send(self, data):
        self.send_calls += 1
        accepted = min(self.short_write_size, len(data))
        self.wire.extend(data[:accepted])
        return accepted

    def sendall(self, data):
        self.sendall_calls += 1
        self.wire.extend(data)


def _xmodem8k_frame():
    modem = XMODEM(lambda _size, _timeout=0.5: None, lambda data, _timeout=0.5: len(data))
    payload = b"x" * 8192
    framed_payload = bytes([len(payload) >> 8, len(payload) & 0xFF]) + payload
    return bytes(modem._make_send_header(8192, 1) + framed_payload + modem._make_send_checksum(1, framed_payload))


def test_putc_sends_the_complete_xmodem_frame_and_returns_its_length():
    stream = WIFIStream.__new__(WIFIStream)
    stream.socket = DeterministicShortWriteSocket(short_write_size=2048)
    frame = _xmodem8k_frame()
    assert len(frame) == 8199, "fixture must model a complete xmodem8k frame"

    result = stream.putc(frame)

    assert len(stream.socket.wire) == len(frame)
    assert bytes(stream.socket.wire) == frame
    assert stream.socket.send_calls == 0
    assert stream.socket.sendall_calls == 1
    assert result == len(frame)
