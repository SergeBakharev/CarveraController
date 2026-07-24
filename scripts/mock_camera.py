#!/usr/bin/python3
"""
Serve a fake machine camera so the live camera view can be exercised without hardware.

Speaks either protocol the controller probes for::

    poetry run python scripts/mock_camera.py --protocol websocket   # port 82, /ws_video
    poetry run python scripts/mock_camera.py --protocol http        # port 81, /stream

Then connect the controller to the host running this script (Connection -> Network...)
and press the camera button. Frames are generated, so no camera is needed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import logging
import math
import socket
import struct
import threading
import time

WEBSOCKET_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BOUNDARY = b"mockcameraframe"
FRAME_SIZE = (640, 480)

logger = logging.getLogger("mock_camera")


def build_frames(count=60):
    """Render a numbered sweeping-bar animation as JPEG bytes."""
    from PIL import Image, ImageDraw

    frames = []
    width, height = FRAME_SIZE
    for index in range(count):
        image = Image.new("RGB", FRAME_SIZE, (24, 24, 32))
        draw = ImageDraw.Draw(image)
        for x in range(0, width, 80):
            draw.line([(x, 0), (x, height)], fill=(48, 48, 60))
        for y in range(0, height, 80):
            draw.line([(0, y), (width, y)], fill=(48, 48, 60))
        offset = (math.sin(index / count * 2 * math.pi) + 1) / 2
        bar_x = int(offset * (width - 60))
        draw.rectangle([bar_x, height // 2 - 30, bar_x + 60, height // 2 + 30], fill=(50, 164, 206))
        draw.text((10, 10), f"mock camera frame {index:03d}", fill=(240, 240, 240))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        frames.append(buffer.getvalue())
    return frames


def server_frame(opcode, payload, fin=True):
    """Encode one unmasked server-to-client WebSocket frame."""
    header = bytearray([(0x80 if fin else 0) | opcode])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65536:
        header.append(126)
        header += struct.pack(">H", len(payload))
    else:
        header.append(127)
        header += struct.pack(">Q", len(payload))
    return bytes(header) + payload


def read_request(conn):
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        request += chunk
    return request


def serve_websocket(conn, frames, fps, fragment):
    request = read_request(conn)
    if request is None:
        return
    key = next(line for line in request.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key")).split(b": ")[1]
    accept = base64.b64encode(hashlib.sha1(key + WEBSOCKET_GUID).digest())
    conn.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n"
    )
    logger.info("websocket handshake complete, waiting for the start message")
    conn.settimeout(5.0)
    if not conn.recv(4096):
        return
    logger.info("streaming %d frames at %.1f fps (fragmented=%s)", len(frames), fps, fragment)
    for index in _forever(len(frames)):
        jpeg = frames[index]
        if fragment:
            half = len(jpeg) // 2
            conn.sendall(server_frame(0x2, jpeg[:half], fin=False))
            conn.sendall(server_frame(0x0, jpeg[half:], fin=True))
        else:
            conn.sendall(server_frame(0x2, jpeg))
        time.sleep(1.0 / fps)


def serve_http(conn, frames, fps, content_length):
    if read_request(conn) is None:
        return
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=" + BOUNDARY + b"\r\n\r\n")
    logger.info("streaming %d frames at %.1f fps (content_length=%s)", len(frames), fps, content_length)
    for index in _forever(len(frames)):
        jpeg = frames[index]
        headers = b"\r\nContent-Type: image/jpeg\r\n"
        if content_length:
            headers += b"Content-Length: %d\r\n" % len(jpeg)
        conn.sendall(b"--" + BOUNDARY + headers + b"\r\n" + jpeg + b"\r\n")
        time.sleep(1.0 / fps)


def _forever(count):
    index = 0
    while True:
        yield index % count
        index += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--protocol", choices=("websocket", "http"), default="websocket")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, help="defaults to 82 for websocket, 81 for http")
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--fragment", action="store_true", help="websocket only: split each frame over two frames")
    parser.add_argument("--no-content-length", action="store_true", help="http only: omit Content-Length from parts")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    port = args.port or (82 if args.protocol == "websocket" else 81)
    frames = build_frames()

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, port))
    listener.listen(1)
    logger.info("serving %s camera on %s:%d, ctrl-c to stop", args.protocol, args.host, port)

    while True:
        conn, peer = listener.accept()
        logger.info("client connected from %s", peer[0])
        handler = serve_websocket if args.protocol == "websocket" else serve_http
        option = args.fragment if args.protocol == "websocket" else not args.no_content_length
        thread = threading.Thread(target=_run_client, args=(handler, conn, frames, args.fps, option), daemon=True)
        thread.start()


def _run_client(handler, conn, frames, fps, option):
    try:
        handler(conn, frames, fps, option)
    except (OSError, StopIteration) as exc:
        logger.info("client gone: %s", exc)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
