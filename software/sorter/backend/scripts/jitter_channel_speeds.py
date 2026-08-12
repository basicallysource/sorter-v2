"""Prove the per-channel feeder move speeds are actually wired through.

Writes a random ±1-10% perturbation to each of C1/C2/C3's move speed, holds it
so you can watch the sorter log, then puts the original values back. It only
ever touches config — it never commands a motor. Start sorting from the UI (so
you keep the stop button) and run this alongside it.

The point is that each channel gets a DIFFERENT jitter, so the log lines prove
the speeds are independent rather than all reading one shared value:

    python3 scripts/jitter_channel_speeds.py --hold 60

Then watch, in another shell:

    journalctl -u sorter -f | grep -o 'PulsePerception: ch[0-9_a-z]* pulse ch=[0-9] speed=[0-9]*'

Each channel's pulses must report the jittered number printed below, and the
three numbers must differ. If every channel logs the same speed, the per-channel
plumbing is not live.

Restores the original speeds on exit, including on Ctrl-C.
"""

import argparse
import atexit
import os
import random
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from subsystems.feeder.pulse_perception.autotune import TUNABLE_PARAMS
from subsystems.feeder.pulse_perception.config import CHANNEL_MOVE_SPEED_KEYS
from toml_config import getPulsePerceptionConfig, setPulsePerceptionConfig

# Keep the jitter inside the same envelope auto-tune is allowed to search, so
# this can never write a speed the tuner itself would refuse to try.
_BOUNDS = {
    meta["key"]: (meta["min"], meta["max"])
    for meta in TUNABLE_PARAMS
    if meta["key"] in set(CHANNEL_MOVE_SPEED_KEYS.values())
}

_MIN_JITTER_PCT = 1.0
_MAX_JITTER_PCT = 10.0


def jitteredSpeed(current: int, rng: random.Random, key: str) -> tuple[int, float]:
    """One channel's perturbed speed and the signed percentage applied. The
    magnitude is always >= 1% so the change is unambiguous in the log, and the
    sign is random per channel so the three channels diverge."""
    pct = rng.uniform(_MIN_JITTER_PCT, _MAX_JITTER_PCT) * rng.choice((-1.0, 1.0))
    value = int(round(current * (1.0 + pct / 100.0)))
    lo, hi = _BOUNDS.get(key, (1, 100000))
    value = min(int(hi), max(int(lo), value))
    if value == current:
        # Clamped back onto the original (channel already at a bound) — nudge it
        # off by a step so the log still shows a distinct number.
        value = current - 1 if current > int(lo) else current + 1
    applied_pct = (value - current) / current * 100.0 if current else 0.0
    return value, applied_pct


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hold",
        type=float,
        default=60.0,
        help="seconds to hold the jittered speeds before restoring (default 60)",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="RNG seed, for a reproducible run"
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    config = getPulsePerceptionConfig()
    original = {key: int(config[key]) for key in CHANNEL_MOVE_SPEED_KEYS.values()}

    restored = False

    def restore(*_a) -> None:
        nonlocal restored
        if restored:
            return
        restored = True
        setPulsePerceptionConfig(original)
        print("\nrestored original speeds:")
        for channel, key in sorted(CHANNEL_MOVE_SPEED_KEYS.items()):
            print(f"  C{channel}  {original[key]}")

    # Any exit path puts the machine back — a half-finished run must never leave
    # a tuned machine on a random speed.
    atexit.register(restore)
    signal.signal(signal.SIGINT, lambda *_a: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_a: sys.exit(0))

    updates: dict[str, int] = {}
    print("jittering per-channel move speeds (±1-10%):\n")
    print(f"  {'channel':<9}{'before':>8}{'after':>8}{'delta':>9}")
    for channel, key in sorted(CHANNEL_MOVE_SPEED_KEYS.items()):
        before = original[key]
        after, pct = jitteredSpeed(before, rng, key)
        updates[key] = after
        print(f"  C{channel:<8}{before:>8}{after:>8}{pct:>8.1f}%")

    setPulsePerceptionConfig(updates)
    print(
        "\napplied. The feeder re-reads config on a ~1s TTL, so the next pulse on "
        "each channel should log its new speed.\n"
    )
    print("watch with:")
    print(
        "  journalctl -u sorter -f | grep -o "
        "'PulsePerception: ch[0-9_a-z]* pulse ch=[0-9] speed=[0-9]*'\n"
    )
    print(f"holding {args.hold:.0f}s — Ctrl-C to restore early.")
    time.sleep(args.hold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
