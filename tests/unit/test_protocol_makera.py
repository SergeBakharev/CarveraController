from carveracontroller.protocols.framing import (
    PTYPE_FILE_MD5,
    PTYPE_LOAD_ERROR,
    PTYPE_LOAD_FINISH,
    PTYPE_LOAD_INFO,
    PTYPE_NORMAL_INFO,
    PTYPE_STATUS_RES,
    build_frame,
)
from carveracontroller.protocols.makera import MakeraProtocol
from carveracontroller.protocols.messages import MessageKind


def test_encode_realtime_and_command():
    proto = MakeraProtocol()
    frame = proto.encode_realtime(ord("?"))
    assert frame[:2] == b"\x86\x68"
    assert frame[-2:] == b"\x55\xaa"

    cmd = proto.encode_command(b"version\n")
    assert cmd[:2] == b"\x86\x68"
    # Trailing newlines must be stripped from CTRL_MULTI payloads (OEM behavior).
    assert b"version\n" not in cmd
    assert b"version" in cmd

    baud = proto.encode_command(b"baud 230400\n")
    assert b"230400\n" not in baud
    assert b"baud 230400" in baud

    file_cmd = proto.encode_file_command(b"upload /sd/a.nc")
    assert file_cmd[:2] == b"\x86\x68"
    # File-start frames keep the trailing newline.
    assert b"upload /sd/a.nc\n" in file_cmd


def test_feed_status_frame():
    proto = MakeraProtocol()
    payload = b"<Idle|MPos:1,2,3>"
    frame = build_frame(PTYPE_STATUS_RES, payload)
    msgs = proto.feed(frame)
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == payload.decode()


def test_feed_normal_info_and_load():
    proto = MakeraProtocol()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"ok\r\n"))
    assert msgs[0].kind == MessageKind.LINE
    assert "ok" in msgs[0].text

    msgs = proto.feed(build_frame(PTYPE_LOAD_INFO, b"file.nc\n"))
    assert msgs[0].kind == MessageKind.LOAD_CHUNK
    assert "file.nc" in msgs[0].text


def test_feed_load_finish_and_error():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_LOAD_FINISH, b"done"))[0].kind == MessageKind.LOAD_EOF
    assert proto.feed(build_frame(PTYPE_LOAD_ERROR, b"err"))[0].kind == MessageKind.LOAD_ERROR


def test_feed_rejects_bad_footer():
    proto = MakeraProtocol()
    frame = bytearray(build_frame(PTYPE_STATUS_RES, b"<Idle>"))
    frame[-1] = 0x00
    assert proto.feed(bytes(frame)) == []


def test_feed_byte_at_a_time():
    proto = MakeraProtocol()
    frame = build_frame(PTYPE_STATUS_RES, b"<Run>")
    msgs = []
    for b in frame:
        msgs.extend(proto.feed(bytes([b])))
    assert len(msgs) == 1
    assert msgs[0].text == "<Run>"


def test_file_transfer_frames_ignored_on_control_channel():
    proto = MakeraProtocol()
    frame = build_frame(PTYPE_FILE_MD5, b"3bc28b19cfca32e413fd9029000117a3")
    assert proto.feed(frame) == []
