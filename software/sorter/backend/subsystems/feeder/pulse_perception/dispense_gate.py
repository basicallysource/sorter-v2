"""One piece per hand-off.

A channel meters its leading piece off the exit a small pulse at a time while
the next channel is ready for it. The next channel only reads "not ready" once
its camera has seen the piece land, some hundreds of milliseconds after the
fall, and in that window another pulse can push the piece behind it off too: a
double drop.

So a channel remembers which piece it is pushing off (its track id). When that
id is gone the piece has fallen, and the exit holds until the next channel shows
it arrived, or until a timeout if it never does (the piece bounced away, or the
camera missed it). Advancing the rest of the channel toward the exit stays
allowed; only exit pulses wait.

A lead piece without a track id cannot be followed; for it the fall is the
moment no piece is left in the exit zone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DispenseGate:
    # The pushed piece's id must stay gone this long to count as fallen, so a
    # one-frame detector blink does not read as a drop.
    vanish_confirm_s: float = 0.15
    # Hold the exit at most this long after a fall while the next channel has
    # not shown the piece.
    arrival_timeout_s: float = 1.5

    # Id of the piece being pushed off; None when nothing is being pushed or the
    # lead is untracked (then ``pushing_untracked`` is set instead).
    track_id: int | None = None
    pushing_untracked: bool = False
    missing_since: float | None = None
    fell_at: float | None = None

    def exitAllowed(self) -> bool:
        """An exit pulse may go out: no fall is awaiting its arrival, and the
        piece being pushed has not just vanished."""
        return self.fell_at is None and self.missing_since is None

    def notePush(self, lead) -> None:
        """An exit pulse went out for ``lead`` (a ``PieceObservation`` or None)."""
        if self.fell_at is not None:
            return
        track_id = getattr(lead, "sv_bt_track_id", None) if lead is not None else None
        if track_id is None:
            if self.track_id is None:
                self.pushing_untracked = True
            return
        if self.track_id != track_id:
            self.track_id = track_id
            self.pushing_untracked = False
            self.missing_since = None

    def observe(self, state, now: float, downstream_arrived: bool) -> bool:
        """Update from this frame. Returns True once, when the pushed piece is
        confirmed to have fallen.

        ``downstream_arrived`` says the next channel shows a new piece (its
        drop zone occupied, or for the classification channel: no longer ready).
        """
        if self.fell_at is not None:
            if downstream_arrived or (now - self.fell_at) >= self.arrival_timeout_s:
                self._reset()
            return False
        if self.track_id is not None:
            ids = {getattr(p, "sv_bt_track_id", None) for p in getattr(state, "pieces", ())}
            if self.track_id in ids:
                self.missing_since = None
                return False
            if self.missing_since is None:
                self.missing_since = now
            if (now - self.missing_since) < self.vanish_confirm_s:
                return False
            return self._fell(now)
        if self.pushing_untracked and not getattr(state, "in_exit", False):
            return self._fell(now)
        return False

    def _fell(self, now: float) -> bool:
        self.fell_at = now
        self.track_id = None
        self.pushing_untracked = False
        self.missing_since = None
        return True

    def _reset(self) -> None:
        self.track_id = None
        self.pushing_untracked = False
        self.missing_since = None
        self.fell_at = None
