"""Parsed messages produced by communication protocol RX parsers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class MessageKind(Enum):
    LINE = auto()
    LOAD_CHUNK = auto()
    LOAD_EOF = auto()
    LOAD_ERROR = auto()


@dataclass(frozen=True)
class ParsedMessage:
    kind: MessageKind
    text: str = ""
