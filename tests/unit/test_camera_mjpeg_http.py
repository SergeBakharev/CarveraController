from carveracontroller.addons.camera.sources.mjpeg_http import parse_part

BOUNDARY = b"frameboundary"
JPEG = b"\xff\xd8\xff\xe0payload\xff\xd9"


def _part(body, content_length=True):
    headers = b"\r\nContent-Type: image/jpeg\r\n"
    if content_length:
        headers += b"Content-Length: %d\r\n" % len(body)
    return b"--" + BOUNDARY + headers + b"\r\n" + body + b"\r\n"


def _drain(stream):
    """Pull every complete frame out of ``stream`` the way the source does."""
    buffer = bytearray(stream)
    frames = []
    while True:
        parsed = parse_part(buffer, BOUNDARY)
        if parsed is None:
            return frames
        jpeg, consumed = parsed
        frames.append(jpeg)
        del buffer[:consumed]


def test_parse_part_uses_content_length_when_present():
    assert _drain(_part(JPEG) * 2) == [JPEG, JPEG]


def test_parse_part_falls_back_to_next_boundary_without_content_length():
    # Without a length a part is only delimited by the following boundary, so the
    # last part on the wire stays pending until the next frame starts arriving.
    assert _drain(_part(JPEG, content_length=False) * 3) == [JPEG, JPEG]


def test_parse_part_returns_none_until_complete():
    stream = _part(JPEG)
    for cut in (0, 5, len(b"--" + BOUNDARY), len(stream) - len(b"\r\n") - 1):
        assert parse_part(stream[:cut], BOUNDARY) is None
    assert parse_part(stream, BOUNDARY) is not None


def test_parse_part_returns_none_when_final_boundary_is_missing():
    assert parse_part(_part(JPEG, content_length=False), BOUNDARY) is None


def test_parse_part_skips_leading_preamble():
    stream = b"garbage before the first boundary\r\n" + _part(JPEG)
    assert parse_part(stream, BOUNDARY)[0] == JPEG
