from carveracontroller.protocols.detector import PROBE_COMMAND, detect_protocol_name


class FakeStream:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self._rx = []

    def send(self, data):
        self.sent.append(data)
        if self.responses:
            self._rx = list(self.responses.pop(0) or b"")

    def getc(self, size, timeout=1):
        if not self._rx:
            return None
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk or None


def test_detect_smoothie_on_echo_response(monkeypatch):
    monkeypatch.setattr("carveracontroller.protocols.detector.time.sleep", lambda *_: None)
    stream = FakeStream([b"echo: echo"])
    assert detect_protocol_name(stream, attempts=3) == "smoothie"
    assert stream.sent[0] == PROBE_COMMAND


def test_detect_makera_on_timeouts(monkeypatch):
    monkeypatch.setattr("carveracontroller.protocols.detector.time.sleep", lambda *_: None)
    stream = FakeStream([None, None, None])
    assert detect_protocol_name(stream, attempts=3) == "makera"
    assert len(stream.sent) == 3


def test_detect_smoothie_on_later_attempt(monkeypatch):
    monkeypatch.setattr("carveracontroller.protocols.detector.time.sleep", lambda *_: None)
    stream = FakeStream([None, b"echo"])
    assert detect_protocol_name(stream, attempts=3) == "smoothie"
