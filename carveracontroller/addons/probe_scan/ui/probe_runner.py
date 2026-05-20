"""Probe lifecycle management: animation, timeout, and run-token tracking."""

from __future__ import annotations

from collections.abc import Callable

from kivy.clock import Clock

from carveracontroller.translation import tr

_PROBE_ANIM_FRAMES = ("◐", "◓", "◑", "◒")
_PROBE_TIMEOUT_S = 30.0


class ProbeRunner:
    """Manages probe animation, timeout, and run-token lifecycle."""

    def __init__(
        self,
        *,
        set_is_probing: Callable[[bool], None],
        set_status_text: Callable[[str], None],
        on_state_changed: Callable[[], None],
        controller_abort: Callable[[], None],
        idle_ok: Callable[[], bool],
    ) -> None:
        self._set_is_probing = set_is_probing
        self._set_status_text = set_status_text
        self._on_state_changed = on_state_changed
        self._controller_abort = controller_abort
        self._idle_ok = idle_ok

        self._gen: int = 0
        self._active_token: int | None = None
        self._anim_event = None
        self._timeout_event = None
        self._anim_frame: int = 0

    def start(self) -> int:
        """Start a probe run. Returns the run token for deferred validation."""
        self._gen += 1
        self._active_token = self._gen
        self._anim_frame = 0
        self._set_is_probing(True)
        self._tick_status()

        if self._anim_event is not None:
            self._anim_event.cancel()
        self._anim_event = Clock.schedule_interval(self._tick_anim, 0.18)

        if self._timeout_event is not None:
            self._timeout_event.cancel()
        saved_token = self._active_token
        self._timeout_event = Clock.schedule_once(
            lambda _dt, t=saved_token: self._on_timeout(_dt, t),
            _PROBE_TIMEOUT_S,
        )
        self._on_state_changed()
        return self._active_token

    def pre_complete(self) -> None:
        """Cancel the timeout immediately (call as soon as a result arrives).

        Safe to call from any thread; just cancels the Kivy Clock event.
        The actual probe state is updated later in ``complete()``.
        """
        if self._timeout_event is not None:
            self._timeout_event.cancel()
            self._timeout_event = None

    def complete(self) -> None:
        """Mark the current probe run as finished (success path)."""
        self._invalidate_token()
        self._clear_events()
        self._set_is_probing(False)
        self._set_status_text("")
        self._on_state_changed()

    def cancel(self, *, abort_machine: bool = False) -> None:
        """Cancel the current probe run and optionally abort the machine."""
        self._invalidate_token()
        self._clear_events()
        if abort_machine and not self._idle_ok():
            self._controller_abort()
        self._set_is_probing(False)
        self._set_status_text("")
        self._on_state_changed()

    def shutdown(self) -> None:
        """Silently cancel all events without firing callbacks (use on popup dismiss)."""
        self._invalidate_token()
        self._clear_events()

    def is_token_valid(self, token: int) -> bool:
        """Return True if *token* matches the currently active run."""
        return token == self._active_token

    def get_active_token(self) -> int | None:
        """Return the current run token, or None if not probing."""
        return self._active_token

    def _invalidate_token(self) -> None:
        self._gen += 1
        self._active_token = None

    def _clear_events(self) -> None:
        if self._anim_event is not None:
            self._anim_event.cancel()
            self._anim_event = None
        if self._timeout_event is not None:
            self._timeout_event.cancel()
            self._timeout_event = None

    def _tick_anim(self, _dt=None) -> None:
        self._anim_frame = (self._anim_frame + 1) % len(_PROBE_ANIM_FRAMES)
        self._tick_status()

    def _tick_status(self) -> None:
        frame = _PROBE_ANIM_FRAMES[self._anim_frame % len(_PROBE_ANIM_FRAMES)]
        self._set_status_text(f"{frame}  {tr._('Probing in progress\u2026')}")

    def _on_timeout(self, _dt=None, run_token: int | None = None) -> None:
        if self._active_token is None:
            return
        if run_token is None or run_token != self._active_token:
            return
        self.cancel(abort_machine=True)
        if self._on_timeout_cb is not None:
            self._on_timeout_cb()

    # Optional timeout notification callback set after construction.
    _on_timeout_cb: Callable[[], None] | None = None

    def set_on_timeout(self, cb: Callable[[], None]) -> None:
        """Register a callback invoked when the probe times out."""
        self._on_timeout_cb = cb
