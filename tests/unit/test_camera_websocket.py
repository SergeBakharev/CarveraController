import struct

from carveracontroller.addons.camera.websocket import (
    OP_BINARY,
    OP_CONTINUATION,
    OP_TEXT,
    build_frame,
    parse_frame,
)


def test_build_frame_masks_payload_with_fin_set():
    mask = b"\x01\x02\x03\x04"
    frame = build_frame(OP_TEXT, b"start_stream", mask=mask)

    assert frame[0] == 0x80 | OP_TEXT
    assert frame[1] == 0x80 | len(b"start_stream")
    assert frame[2:6] == mask
    payload = frame[6:]
    assert payload != b"start_stream"
    assert bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) == b"start_stream"


def test_build_frame_extended_lengths():
    medium = build_frame(OP_BINARY, b"\x00" * 200)
    assert medium[1] == 0x80 | 126
    assert struct.unpack_from(">H", medium, 2)[0] == 200

    large = build_frame(OP_BINARY, b"\x00" * 70000)
    assert large[1] == 0x80 | 127
    assert struct.unpack_from(">Q", large, 2)[0] == 70000


def test_parse_frame_round_trips_build_frame():
    for payload in (b"", b"jpeg", b"\x00" * 200, b"\xff" * 70000):
        raw = build_frame(OP_BINARY, payload)
        frame, consumed = parse_frame(raw)

        assert consumed == len(raw)
        assert frame.fin is True
        assert frame.opcode == OP_BINARY
        assert frame.payload == payload


def test_parse_frame_returns_none_until_complete():
    raw = build_frame(OP_BINARY, b"\x00" * 300)

    for cut in (0, 1, 2, 3, 7, len(raw) - 1):
        assert parse_frame(raw[:cut]) is None

    assert parse_frame(raw) is not None


def test_parse_frame_reports_fragments_and_leaves_trailing_bytes():
    first = bytes([OP_BINARY, 4]) + b"head"
    last = bytes([0x80 | OP_CONTINUATION, 4]) + b"tail"

    frame, consumed = parse_frame(first + last)
    assert frame.fin is False
    assert frame.opcode == OP_BINARY
    assert frame.payload == b"head"
    assert consumed == len(first)

    frame, consumed = parse_frame((first + last)[consumed:])
    assert frame.fin is True
    assert frame.opcode == OP_CONTINUATION
    assert frame.payload == b"tail"
    assert consumed == len(last)
