"""Generation token for probe scan operations."""

class ProbeRunToken:
    """
    Generation counter for probe runs.
    Each probe call ``start()`` bumps the generation and returns the token. Callers should store that value and compare deferred handlers to it.
    A call to ``invalidate()`` bumps again so any handler still using ``current()`` is ignored after cancel or successful completion.
    """

    def __init__(self) -> None:
        self._gen = 0

    def start(self) -> int:
        self._gen += 1
        return self._gen

    def current(self) -> int:
        return self._gen

    def is_current(self, token: int) -> bool:
        return token == self._gen

    def invalidate(self) -> None:
        self._gen += 1
