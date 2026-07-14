"""Registry of CAM tool table parsers and the extraction entry point."""

import logging

from carveracontroller.addons.tool_visualization.parsers.fusion360_makera import Fusion360MakeraParser

logger = logging.getLogger(__name__)

# Ordered list of parsers to try when extracting a tool table from a loaded
# G-code file. Add new CAM/post-processor parsers here.
TOOL_TABLE_PARSERS = [
    Fusion360MakeraParser(),
]


def extract_tool_table(lines):
    """Try each registered parser and return the first non-empty tool table.

    `lines` is passed as-is to each parser; well-behaved parsers bail out
    early (e.g. via `ToolTableParser.iter_header_lines`) instead of scanning
    the whole file, so this stays cheap even for very large files.

    Returns a dict mapping tool number (int) -> ToolDefinition. If no parser
    recognises the file (or the file has no tool table at all), an empty
    dict is returned; callers should then fall back to default tool
    geometry for every tool.
    """
    for parser in TOOL_TABLE_PARSERS:
        try:
            tool_table = parser.parse(lines)
        except Exception:
            logger.exception(f"Tool table parser '{parser.name}' raised an exception, skipping it")
            tool_table = {}
        if tool_table:
            tool_numbers = ", ".join(f"T{number}" for number in sorted(tool_table))
            logger.info(f"Tool table extracted using parser '{parser.name}': {tool_numbers}")
            return tool_table

    logger.debug("No tool table detected in loaded file (no parser recognised it); using default tool geometry")
    return {}
