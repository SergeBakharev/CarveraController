"""Tests for whole-file integrity checks in XMODEM downloads."""

import hashlib
from io import BytesIO

from carveracontroller.XMODEM import ACK, CAN, CRC, EOT, XMODEM


def _packet(modem, sequence, payload):
    packet_size = 8192
    header = modem._make_send_header(packet_size, sequence)
    data = bytes([len(payload) >> 8, len(payload) & 0xFF]) + payload.ljust(packet_size, modem.pad)
    checksum = modem._make_send_checksum(1, data)
    return bytes(header + data + checksum)


def _receive(expected_payload, received_payload, local_md5=""):
    transport = BytesIO()
    writes = []

    def getc(size, timeout=0.5):
        return transport.read(size) or None

    def putc(data, timeout=0.5):
        writes.append(data)
        return len(data)

    modem = XMODEM(getc, putc, "xmodem8k")
    expected_md5 = hashlib.md5(expected_payload).hexdigest().encode()
    transport.write(_packet(modem, 0, expected_md5))
    if received_payload:
        transport.write(_packet(modem, 1, received_payload))
    transport.write(EOT)
    transport.seek(0)

    output = BytesIO()
    result = modem.recv(output, md5=local_md5)
    return result, output.getvalue(), writes


def test_recv_accepts_download_matching_block_zero_md5():
    payload = b"G0 X1 Y2\nM2\n"

    result, output, writes = _receive(payload, payload)

    assert result is not None
    assert result > 0
    assert output == payload
    assert writes == [CRC, ACK, ACK, ACK]


def test_recv_short_circuits_when_uppercase_local_md5_matches_block_zero():
    payload = b"G0 X1 Y2\nM2\n"
    local_md5 = hashlib.md5(payload).hexdigest().upper()

    result, output, writes = _receive(payload, payload, local_md5=local_md5)

    assert result == 0
    assert output == b""
    assert writes == [CRC, CAN, CAN, CAN]


def test_recv_rejects_eot_when_download_does_not_match_block_zero_md5():
    expected_payload = b"G0 X1 Y2\nG1 X3 Y4\nM2\n"
    truncated_payload = b"G0 X1 Y2\n"

    result, output, writes = _receive(expected_payload, truncated_payload)

    assert result is None
    assert output == truncated_payload
    # Transport completion remains wire-compatible even though the local
    # artifact is rejected after its whole-file digest is checked.
    assert writes == [CRC, ACK, ACK, ACK]
