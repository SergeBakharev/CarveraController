"""
Live camera stream session.

A camera is found by trying each known endpoint until one answers, and the
source it returns yields whole JPEG frames from then on. The stream needs a
network connection because it does not exist on the serial link, and no source
carries camera parameter controls, so it is view-only.

Frames are read on a worker thread; callbacks are dispatched on the Kivy main
thread.
"""

import logging
import threading

from kivy.clock import Clock

from carveracontroller.addons.camera.endpoints import CAMERA_ENDPOINTS
from carveracontroller.addons.camera.sources.base import CameraStreamClosed
from carveracontroller.translation import tr

CONNECT_TIMEOUT = 5.0
PROBE_TIMEOUT = 1.5

logger = logging.getLogger(__name__)


def find_camera(host, endpoints=CAMERA_ENDPOINTS, timeout=PROBE_TIMEOUT):
    """Return the first endpoint that a camera answers on ``host``, else None.

    Blocks for up to ``timeout`` per endpoint, so call it off the main thread.
    """
    for endpoint in endpoints:
        try:
            source = endpoint.open(host, timeout)
        except OSError as exc:
            logger.info("No %s camera at %s:%d%s (%s)", endpoint.source.name, host, endpoint.port, endpoint.path, exc)
            continue
        source.close()
        return endpoint
    return None


class CameraStream:
    """Owns the reader thread for one camera session.

    ``on_frame`` receives complete JPEG bytes, ``on_streaming`` the current
    streaming state and ``on_error`` a user-facing message.
    """

    def __init__(self, on_frame, on_streaming, on_error):
        self._on_frame = on_frame
        self._on_streaming = on_streaming
        self._on_error = on_error
        self._source = None
        self._streaming = False
        self._session = 0

    def is_streaming(self):
        return self._streaming

    def start(self, host, endpoint):
        if self._streaming:
            return
        self._session += 1
        self._streaming = True
        self._notify(self._on_streaming, True)
        threading.Thread(target=self._read_frames, args=(host, endpoint, self._session), daemon=True).start()

    def stop(self):
        """Invalidate the running worker's session, then close its source."""
        if not self._streaming:
            return
        self._session += 1
        self._streaming = False
        source, self._source = self._source, None
        if source is not None:
            source.close()
        self._notify(self._on_streaming, False)

    def _read_frames(self, host, endpoint, session):
        """Forward frames until stopped, closed, or superseded by a newer session.

        The source is only ever reached through the local ``source``, so a newer
        session replacing ``self._source`` can neither be read nor torn down
        here.
        """
        source = None
        try:
            source = endpoint.open(host, CONNECT_TIMEOUT)
            self._source = source
            logger.info(
                "Camera stream connected: %s at %s:%d%s", endpoint.source.name, host, endpoint.port, endpoint.path
            )
            while self._streaming and self._session == session:
                jpeg = source.next_frame()
                if jpeg is not None:
                    self._notify(self._on_frame, jpeg)
        except CameraStreamClosed:
            logger.info("Camera stream closed by the machine")
        except OSError as exc:
            if self._streaming and self._session == session:
                logger.error("Camera stream failed: %s", exc)
                self._notify(self._on_error, tr._("Camera stream error: {}").format(exc))
        finally:
            if source is not None:
                source.close()
            if self._session == session:
                self._source = None
                self._streaming = False
                self._notify(self._on_streaming, False)

    def _notify(self, callback, value):
        Clock.schedule_once(lambda _dt: callback(value), 0)
