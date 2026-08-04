import struct

from carveracontroller.addons.camera.websocket import OP_BINARY, OP_CONTINUATION, OP_TEXT, build_frame, parse_frame


def test_build_frame_wire_format():
    mask = b"\x01\x02\x03\x04"
    frame = build_frame(OP_TEXT, b"start_stream", mask=mask)
    assert frame[0] == 0x80 | OP_TEXT
    assert frame[1] == 0x80 | len(b"start_stream")
    assert frame[2:6] == mask
    assert bytes(b ^ mask[i % 4] for i, b in enumerate(frame[6:])) == b"start_stream"

    medium = build_frame(OP_BINARY, b"\x00" * 200)
    assert medium[1] == 0x80 | 126
    assert struct.unpack_from(">H", medium, 2)[0] == 200

    large = build_frame(OP_BINARY, b"\x00" * 70000)
    assert large[1] == 0x80 | 127
    assert struct.unpack_from(">Q", large, 2)[0] == 70000


def test_parse_frame_decodes_unmasked_server_frames():
    small = bytes([0x80 | OP_BINARY, 4]) + b"jpeg"
    frame, consumed = parse_frame(small)
    assert (frame.fin, frame.opcode, frame.payload) == (True, OP_BINARY, b"jpeg")
    assert consumed == len(small)

    payload = b"\xff" * 70000
    extended = bytes([0x80 | OP_BINARY, 127]) + struct.pack(">Q", len(payload)) + payload
    frame, consumed = parse_frame(extended)
    assert frame.payload == payload
    assert consumed == len(extended)


def test_parse_frame_returns_none_until_complete():
    raw = bytes([0x80 | OP_BINARY, 126]) + struct.pack(">H", 300) + b"\x00" * 300
    for cut in (0, 1, 2, 3, len(raw) - 1):
        assert parse_frame(raw[:cut]) is None
    assert parse_frame(raw) is not None


def test_parse_frame_reports_fragments_and_leaves_trailing_bytes():
    first = bytes([OP_BINARY, 4]) + b"head"
    last = bytes([0x80 | OP_CONTINUATION, 4]) + b"tail"

    frame, consumed = parse_frame(first + last)
    assert (frame.fin, frame.opcode, frame.payload) == (False, OP_BINARY, b"head")
    assert consumed == len(first)

    frame, consumed = parse_frame((first + last)[consumed:])
    assert (frame.fin, frame.opcode, frame.payload) == (True, OP_CONTINUATION, b"tail")
    assert consumed == len(last)
