"""Start a pretend v1.5 distribution board: `python -m hardware.sim --help`
(from the backend directory). It runs until stopped (Ctrl-C)."""

from __future__ import annotations

import argparse
import signal
import threading

from . import scenarios
from .board import SimBoard

DEFAULT_CONTROL = "/tmp/sorter-sim/control.sock"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m hardware.sim", description=__doc__)
    parser.add_argument(
        "--scenario",
        default="four-doors",
        help=f"the world to start in: a JSON file, or one of {', '.join(sorted(scenarios.BUILT_IN))} "
        "(servos on the board's bus; default four-doors)",
    )
    parser.add_argument("--speed", type=float, help="how much faster than real time the world runs (default 1)")
    parser.add_argument("--link", help="keep a symlink to the board's terminal here, e.g. /tmp/sorter-sim/board")
    parser.add_argument("--adapter", action="store_true", help="also pretend to be a USB servo adapter")
    parser.add_argument(
        "--adapter-scenario", help="the adapter's servos: a built-in name or a file's board_servos (default: none)"
    )
    parser.add_argument("--adapter-echo", action="store_true", help="the adapter hears what it sends")
    parser.add_argument("--adapter-link", help="keep a symlink to the adapter's terminal here")
    parser.add_argument("--control", default=DEFAULT_CONTROL, help=f"the control socket (default {DEFAULT_CONTROL})")
    args = parser.parse_args(argv)

    scenario = scenarios.load(args.scenario)
    if args.adapter_scenario:
        scenario["adapter_servos"] = scenarios.servo_list(args.adapter_scenario)
    board = SimBoard(
        scenario=scenario,
        speed=args.speed,
        adapter=args.adapter or bool(args.adapter_scenario) or bool(args.adapter_link),
        adapter_echo=args.adapter_echo,
        link=args.link,
        adapter_link=args.adapter_link,
        control_path=args.control,
    )
    done = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: done.set())
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    board.start()
    linked = f" (linked at {args.link})" if args.link else ""
    print(f"Pretend v1.5 distribution board on {board.board_path}{linked}", flush=True)
    if board.adapter_port is not None:
        linked = f" (linked at {args.adapter_link})" if args.adapter_link else ""
        echo = ", echoing" if args.adapter_echo else ""
        print(f"Pretend servo adapter on {board.adapter_path}{linked}{echo}", flush=True)
    print(f"Control channel on {args.control}: python -m hardware.sim.ctl --control {args.control} list", flush=True)
    try:
        while not done.wait(0.5):
            pass
    finally:
        board.stop()
        print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
