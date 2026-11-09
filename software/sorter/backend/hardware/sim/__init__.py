"""A pretend control board, so the backend and its set-up screens can be built
and tested with no hardware. See README.md beside this file.

- `framing`: the board's side of the host framing (COBS, CRC32, header).
- `firmware`: the firmware's command tables and replies, for a v1.5 board.
- `world`: the clock and everything that moves; `steppers` (motion and TMC2209
  drivers), `servos` (Feetech servos and the line they share), the chute.
- `ports`: the pseudo-terminals the host opens: the board, and a USB servo adapter.
- `control`, `ctl`: changing the world while it runs.
- `scenarios`: the worlds it can start in.
- `board`: all of it put together; `__main__`: `python -m hardware.sim`.
"""
