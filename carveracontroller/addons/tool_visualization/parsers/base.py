"""Base class for CAM tool table parsers."""

from abc import ABC, abstractmethod

# Characters that make a line "safe" to skip over while looking for a tool
# table header (comment, blank, program-marker or variable-assignment lines).
# Mirrors the characters CNC.parseLine() itself treats as non-motion lines.
HEADER_SAFE_PREFIXES = ("%", "(", "#", ";")

# Hard cap on how many lines a header scan will ever look at, in case a file
# has an unusually long run of leading comments with no actual G-code.
MAX_HEADER_LINES = 5000


class ToolTableParser(ABC):
    """Extracts a tool table from the raw lines of a G-code file.

    Implementations should be conservative: if the file does not look like
    it was produced by the CAM/post processor they support, `parse()` should
    return an empty dict rather than guessing.
    """

    name = "base"

    @abstractmethod
    def parse(self, lines):
        """Parse (an iterable of) raw G-code file lines.

        Returns a dict mapping tool number (int) -> ToolDefinition. If a
        tool number appears in multiple comments, only the first occurrence
        found in the file should be kept.
        """
        raise NotImplementedError

    @staticmethod
    def iter_header_lines(lines, max_lines=MAX_HEADER_LINES):
        """Lazily yield the leading blank/comment-only lines of a file.

        CAM post processors write tool tables as a block of comments at the
        very top of the file, before any real G-code. So instead of scanning
        the whole (potentially huge) file, parsers that rely on this stop
        pulling from `lines` as soon as the first "real" line is seen (or
        after `max_lines`), without ever materialising a separate list.
        """
        for count, line in enumerate(lines):
            if count >= max_lines:
                return
            stripped = line.strip()
            if stripped and stripped[0] not in HEADER_SAFE_PREFIXES:
                return
            yield line
