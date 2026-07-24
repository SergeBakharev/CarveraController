"""Detect which communication protocol the connected machine is using."""

from __future__ import annotations

import logging
import time
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

PROBE_COMMAND = b"echo echo\n"
PROBE_ATTEMPTS = 3
PROBE_WAIT_S = 0.1
PROBE_READ_SIZE = 10


@runtime_checkable
class ProbeStream(Protocol):
    def send(self, data: bytes) -> object: ...

    def getc(self, size: int, timeout: float = 1) -> bytes | None: ...


def _flush_rx(stream: ProbeStream) -> None:
    """Drain any pending bytes from the transport."""
    while True:
        data = stream.getc(1, timeout=0.01)
        if not data:
            break


def detect_protocol_name(stream: ProbeStream, attempts: int = PROBE_ATTEMPTS) -> str:
    """
    Probe the machine with a raw ASCII echo command.

    OEM-compatible behaviour:
      - plaintext response containing ``echo`` → ``smoothie``
      - ``attempts`` empty/timeout responses → ``makera``
    """
    _flush_rx(stream)
    timeouts = 0
    for _ in range(attempts):
        try:
            stream.send(PROBE_COMMAND)
            time.sleep(PROBE_WAIT_S)
            echo = stream.getc(PROBE_READ_SIZE, timeout=PROBE_WAIT_S)
        except Exception:
            logger.debug("Protocol probe send/recv failed", exc_info=True)
            timeouts += 1
            continue

        if echo is not None and b"echo" in echo:
            logger.info("Detected smoothie communication protocol")
            return "smoothie"

        timeouts += 1

    logger.info("Detected makera communication protocol (no echo response)")
    return "makera"
