"""CAM-specific tool table parsers.

Each parser knows how to recognise and extract tool metadata from the
comments a particular CAM software / post processor writes at the top of a
G-code file. Add new parsers here and register them in
`carveracontroller.addons.tool_visualization.extractor.TOOL_TABLE_PARSERS`.

Available parsers:
- fusion360_makera: Fusion 360 Makera post processor tool comments
- makera_studio: Makera Studio `;@MKR|TOOL|...` metadata block
- freecad_makera: FreeCAD Makera post processor `(@FC|TOOL|...)` metadata block
"""
