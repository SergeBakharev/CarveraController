"""Protocol registry — register new protocols here to make them selectable."""

from __future__ import annotations

from .base import CommunicationProtocol
from .makera import MakeraProtocol
from .smoothie import SmoothieProtocol

# Map of protocol name -> implementation class.
# To add a third protocol: implement CommunicationProtocol and register it here.
PROTOCOL_CLASSES: dict[str, type[CommunicationProtocol]] = {
    "smoothie": SmoothieProtocol,
    "makera": MakeraProtocol,
}

DEFAULT_PROTOCOL = "makera"


def available_protocols() -> tuple[str, ...]:
    return tuple(PROTOCOL_CLASSES.keys())


def create_protocol(name: str) -> CommunicationProtocol:
    """Instantiate a protocol by registered name."""
    try:
        cls = PROTOCOL_CLASSES[name]
    except KeyError as exc:
        known = ", ".join(sorted(PROTOCOL_CLASSES))
        raise ValueError(f"Unknown protocol {name!r}; known: {known}") from exc
    return cls()


def register_protocol(name: str, cls: type[CommunicationProtocol]) -> None:
    """Register or replace a protocol implementation (useful for tests / future protocols)."""
    if not issubclass(cls, CommunicationProtocol):
        raise TypeError("cls must be a CommunicationProtocol subclass")
    PROTOCOL_CLASSES[name] = cls
