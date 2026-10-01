"""Z1 timelapse status parsing and the camera-button recording details."""

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.timelapse import format_timelapse_status, timelapse_capture_active


def _parse_status_line(line):
    controller = Controller(CNC(), lambda _line: None, False)
    controller.parseBracketAngle(line)


def test_timelapse_status_fields():
    _parse_status_line("<Run|MPos:0,0,0|WPos:0,0,0|E:1,1,1,1234,5678|OTA:2,40>")
    assert CNC.vars["state"] == "Run"
    assert CNC.vars["tl_status"] == 1
    assert CNC.vars["tl_transfer"] == 1
    assert CNC.vars["tl_requested"] == 1
    assert CNC.vars["tl_recording"] == 1
    assert CNC.vars["tl_sd_used"] == 1234
    assert CNC.vars["tl_sd_total"] == 5678
    assert CNC.vars["ota_phase"] == 2
    assert CNC.vars["ota_progress"] == 40
    assert timelapse_capture_active(CNC.vars["tl_requested"], CNC.vars["state"]) is True


def test_status_without_timelapse_extension_clears_fields():
    CNC.vars["tl_status"] = 1
    CNC.vars["tl_requested"] = 1
    CNC.vars["tl_recording"] = 1
    CNC.vars["ota_phase"] = 4
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0>")
    assert CNC.vars["tl_status"] == 0
    assert CNC.vars["tl_requested"] == 0
    assert CNC.vars["tl_recording"] == 0
    assert CNC.vars["ota_phase"] == 0
    assert CNC.vars["ota_progress"] == 0


def test_recording_mark_requires_request_and_running():
    assert timelapse_capture_active(1, "Run") is True
    assert timelapse_capture_active(1, "Idle") is False
    assert timelapse_capture_active(1, "Hold") is False
    assert timelapse_capture_active(0, "Run") is False


def test_timelapse_status_reports_e_fields():
    text = format_timelapse_status(
        transfer=0,
        requested=1,
        recording=1,
        sd_used=1200,
        sd_total=8192,
    )
    assert text == "\n".join(
        [
            "Auto Timelapse: on",
            "Recording: yes",
            "File transfer: idle",
            "SD card space: 1200 / 8192 MiB",
        ]
    )
