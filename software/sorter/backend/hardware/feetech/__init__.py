"""Feetech serial bus servos (the SC and STS series), however they are reached.

- `registers`: what the bytes in a servo mean, per series and model.
- `link`: one servo conversation at a time, and the guarded moves a link offers.
  A link is the control board's own servo bus (`board_link`) or a USB adapter
  (`adapter_link`); everything above a link is the same for both.
- `guard`: the guard a control board runs in its firmware, in Python, for links
  with no board to run it.
- `servo`: one servo on a link: who it is, where it is, moving it safely.
"""
