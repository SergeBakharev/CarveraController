"""Tests for the G-code helpers exposed by the CNC module."""

from carveracontroller.CNC import detect_document_unit, unit_scale_to_mm


class TestDocumentUnit:
    def test_detects_g21_as_mm(self):
        assert detect_document_unit(["G90 G94\n", "G17\n", "G21\n", "G0 X0\n"]) == "mm"

    def test_detects_g20_as_inches(self):
        assert detect_document_unit(["G90\n", "G20\n", "G0 X1\n"]) == "in"

    def test_defaults_to_mm_when_absent(self):
        assert detect_document_unit(["G90 G94\n", "G0 X10\n"]) == "mm"

    def test_ignores_unit_command_inside_paren_comment(self):
        assert detect_document_unit(["(G20 inches)\n", "G21\n", "G0 X0\n"]) == "mm"

    def test_ignores_unit_command_inside_semicolon_comment(self):
        assert detect_document_unit(["; G20\n", "G21\n"]) == "mm"

    def test_accepts_lowercase_and_leading_zeros(self):
        assert detect_document_unit(["g020\n"]) == "in"
        assert detect_document_unit(["g021\n"]) == "mm"

    def test_unit_scale_to_mm(self):
        assert unit_scale_to_mm("mm") == 1.0
        assert unit_scale_to_mm("in") == 25.4
        assert unit_scale_to_mm("unknown") == 1.0
