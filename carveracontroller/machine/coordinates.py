"""Operations for setting WCS axis offsets, rapid A axis moves, and tool number
selection."""

from typing import Optional, Protocol


class CoordinateController(Protocol):
    def wcs_set(
        self,
        x: Optional[float],
        y: Optional[float],
        z: Optional[float],
        a: Optional[float],
    ) -> None: ...

    def wcs_set_a(self, a: float) -> None: ...

    def rapid_move_a(self, a: float) -> None: ...

    def set_tool_command(self, value: str) -> None: ...

    def change_tool_command(self, value: str) -> None: ...


def set_x_offset(controller: CoordinateController, value: float) -> None:
    controller.wcs_set(value, None, None, None)


def set_y_offset(controller: CoordinateController, value: float) -> None:
    controller.wcs_set(None, value, None, None)


def set_z_offset(controller: CoordinateController, value: float) -> None:
    controller.wcs_set(None, None, value, None)


def set_a_offset(controller: CoordinateController, value: float) -> None:
    controller.wcs_set_a(value)


def rapid_move_a(controller: CoordinateController, value: float) -> None:
    controller.rapid_move_a(value)


def set_tool_number(controller: CoordinateController, value: str) -> None:
    """Set the current tool number without performing a tool change."""
    controller.set_tool_command(value)


def change_tool(controller: CoordinateController, tool_number: str) -> None:
    """Change to the given tool number, executing the tool-change sequence."""
    controller.change_tool_command(tool_number)
