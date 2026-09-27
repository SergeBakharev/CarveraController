"""Z1 timelapse fields carried on the machine status report.

The firmware appends this suffix before the closing ``>``:

``|E:<transfer>,<record-requested>,<recording>,<sd-used>,<sd-total>|OTA:<phase>,<progress>``

Recording captures frames only while it has been requested and the machine is
running a job. The red recording mark uses that combination. The camera
settings panel shows the ``|E:`` fields while it is open.
"""

from __future__ import annotations

from typing import Callable

Translate = Callable[[str], str]


def timelapse_capture_active(requested: int, machine_state: str) -> bool:
    """True when timelapse is armed and the machine is running a job."""
    return bool(requested) and machine_state == "Run"


def format_timelapse_status(
    *,
    transfer: int,
    requested: int,
    recording: int,
    sd_used: int,
    sd_total: int,
    translate: Translate = lambda text: text,
) -> str:
    """Recording details from the ``|E:`` status fields, for the camera settings panel."""
    t = translate
    lines = [
        t("Auto Timelapse: on") if requested else t("Auto Timelapse: off"),
        t("Recording: yes") if recording else t("Recording: no"),
        t("File transfer: active") if transfer else t("File transfer: idle"),
        t("SD card space: %s / %s MiB") % (sd_used, sd_total),
    ]
    return "\n".join(lines)
