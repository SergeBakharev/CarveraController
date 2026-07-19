from carveracontroller.protocols.messages import MessageKind
from carveracontroller.protocols.smoothie import SmoothieProtocol


def test_encode_command_adds_newline():
    proto = SmoothieProtocol()
    assert proto.encode_command(b"version") == b"version\n"
    assert proto.encode_command(b"version\n") == b"version\n"


def test_encode_realtime_and_file_command():
    proto = SmoothieProtocol()
    assert proto.encode_realtime(ord("?")) == b"?"
    assert proto.encode_file_command(b"upload /sd/a.nc") == b"upload /sd/a.nc\n"


def test_feed_newline_line():
    proto = SmoothieProtocol()
    msgs = proto.feed(b"<Idle|MPos:0,0,0>\n")
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == "<Idle|MPos:0,0,0>"


def test_feed_incremental():
    proto = SmoothieProtocol()
    assert proto.feed(b"hel") == []
    msgs = proto.feed(b"lo\n")
    assert len(msgs) == 1
    assert msgs[0].text == "hello"


def test_feed_eot_and_can():
    proto = SmoothieProtocol()
    msgs = proto.feed(b"partial" + b"\x04")
    assert msgs[0].kind == MessageKind.LOAD_CHUNK
    assert msgs[0].text == "partial"
    assert msgs[1].kind == MessageKind.LOAD_EOF

    proto.reset()
    msgs = proto.feed(b"\x16")
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LOAD_ERROR
