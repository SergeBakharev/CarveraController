"""Base class for camera stream sources."""

from abc import ABC, abstractmethod

# How long a source waits for the next frame before reporting that none arrived,
# so the stream worker stays responsive to a stop request between frames.
READ_TIMEOUT = 1.0


class CameraStreamClosed(Exception):
    """The camera ended the stream in an orderly way."""


class CameraSource(ABC):
    """Connects to a camera and yields whole JPEG frames.

    Implementations connect while being constructed and must not block for
    longer than the ``timeout`` they are given, so failing to reach a camera
    surfaces as an ``OSError`` and construction doubles as a probe.
    """

    name = "base"

    @abstractmethod
    def __init__(self, host, port, path, timeout):
        raise NotImplementedError

    @abstractmethod
    def next_frame(self):
        """Return the next whole JPEG frame, or None if none has arrived yet.

        Raises ``CameraStreamClosed`` when the camera ends the stream, and
        ``OSError`` on transport failures.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self):
        """Release the connection; safe to call more than once."""
        raise NotImplementedError
