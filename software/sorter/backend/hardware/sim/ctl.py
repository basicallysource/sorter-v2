"""Change a running pretend board's world: `python -m hardware.sim.ctl --help`.

    python -m hardware.sim.ctl list
    python -m hardware.sim.ctl plug --id 1 --lower 150 --upper 850
    python -m hardware.sim.ctl turn s1 300
    python -m hardware.sim.ctl hall active
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .control import request

DEFAULT_CONTROL = "/tmp/sorter-sim/control.sock"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hardware.sim.ctl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--control",
        default=os.environ.get("SORTER_SIM_CONTROL", DEFAULT_CONTROL),
        help=f"the sim's control socket (default $SORTER_SIM_CONTROL or {DEFAULT_CONTROL})",
    )
    commands = parser.add_subparsers(dest="cmd", required=True, metavar="command")

    def command(name: str, text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=text, description=text)
        return sub

    def servo(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("servo", help="its label (see list), or its ID if only one servo has it")
        sub.add_argument("--bus", choices=("board", "adapter"), help="look only on this bus")

    def bus(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--bus", choices=("board", "adapter"), help="which servo bus (default board)")

    command("list", "show the whole world")

    sub = command("plug", "plug in a new servo, or plug an unplugged one back in by its label")
    sub.add_argument("servo", nargs="?", help="the label of an unplugged servo")
    sub.add_argument("--id", type=int, help="a new servo's ID (new servos come as 1)")
    sub.add_argument("--model", choices=("SC15", "SC09", "STS3215"))
    sub.add_argument("--position", type=float, help="where it sits, in its counts")
    sub.add_argument("--lower", type=float, help="its lower hard stop")
    sub.add_argument("--upper", type=float, help="its upper hard stop")
    sub.add_argument("--label", help="a name for it")
    bus(sub)

    servo(command("unplug", "unplug a servo: it falls silent"))

    sub = command("turn", "turn a door by hand (only while its torque is off)")
    servo(sub)
    sub.add_argument("position", type=float)

    sub = command("block", "put something in a door's way at a position")
    servo(sub)
    sub.add_argument("position", type=float)

    sub = command("unblock", "take a block out of a door's way (all of them, or the one at a position)")
    servo(sub)
    sub.add_argument("position", type=float, nargs="?")

    sub = command("stops", "move a door's hard stops")
    servo(sub)
    sub.add_argument("lower", type=float)
    sub.add_argument("upper", type=float)

    sub = command("servo-power", "cut or restore the servos' power")
    sub.add_argument("state", choices=("on", "off"))
    bus(sub)

    sub = command("line", "hold the servo line low (stuck), or let it go (ok)")
    sub.add_argument("state", choices=("stuck", "ok"))
    bus(sub)

    sub = command("hall", "hold the chute's hall sensor active or inactive, or let the magnet decide (auto)")
    sub.add_argument("state", choices=("active", "inactive", "auto"))

    sub = command("magnet", "move the chute's magnet window")
    sub.add_argument("angle", type=float, help="the middle of the window, in chute degrees")
    sub.add_argument("--width", type=float, help="its width, in degrees")

    sub = command("chute-angle", "turn the chute by hand to an angle")
    sub.add_argument("angle", type=float)

    sub = command("board", "make the board stop answering (silent), or answer again")
    sub.add_argument("state", choices=("silent", "answer"))

    sub = command("motor-power", "cut or restore the stepper drivers' power")
    sub.add_argument("state", choices=("on", "off"))

    sub = command("speed", "run the world faster or slower than real time")
    sub.add_argument("speed", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = vars(_parser().parse_args(argv))
    control = args.pop("control")
    payload = {key: value for key, value in args.items() if value is not None}
    try:
        reply = request(control, payload)
    except OSError as exc:
        print(f"No pretend board answers on {control}: {exc}", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(reply.get("error"), file=sys.stderr)
        return 1
    print(json.dumps(reply.get("result"), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
