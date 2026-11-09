# A pretend control board

`hardware/sim` pretends to be a v1.5 distribution control board, so the
backend and its set-up screens can be developed and tested with no hardware.
It opens a pseudo-terminal that the backend opens as if it were the board's
serial port, and answers there exactly as the board's firmware does: the same
framing, command codes, payloads, replies and error replies
(`software/firmware/sorter_interface_firmware/`). The backend's own code
(`MCUBus`, `SorterInterface`, `BoardServoLink`) talks to it unchanged.

Behind it is a small world that moves in real time:

- **Five steppers** with the v1.5 board's names (`chute_stepper`,
  `c_channel_1_rotor`, `c_channel_3_rotor`, `carousel`, `c_channel_2_rotor`).
  They take time to move, using the firmware's own speed and acceleration ramps,
  and their positions can be read while they move. Each has a TMC2209 driver
  whose registers read back what was written, and whose write counter (IFCNT)
  counts every write, so the backend's driver set-up and its check pass.
- **The chute**: its stepper turns it through a 6:1 drive (9,600 microsteps a
  turn at 8 microsteps), without limit. A hall sensor on digital input 0 reads
  active (low) while the chute is inside an 18 degree magnet window, at 0 degrees
  by default; the chute starts at 120 degrees. `HOME` runs until the input reads
  the level asked for, stops dead and zeroes the count, as the firmware does.
- **Serial bus servos** on the board's servo bus: Feetech SC15s by default, each
  with an ID, a position and two hard stops (the ends of a door's travel). The
  board's guard watches moves and probes (the firmware's `ServoGuard`, ported
  to Python in `hardware/feetech/guard.py`). Two servos with the same ID answer
  at once and garble each other, as on a real bus; brand-new servos all have
  ID 1. An unplugged or unpowered servo is silent.
- **Optionally, a pretend USB servo adapter**: a second pseudo-terminal that
  speaks raw Feetech packets to servos of its own, for
  `hardware/feetech/adapter_link.py`.

## Start it

From `software/sorter/backend`:

```sh
uv run python -m hardware.sim --link /tmp/sorter-sim/board
```

It prints where the board is and keeps running until Ctrl-C:

```
Pretend v1.5 distribution board on /dev/pts/4 (linked at /tmp/sorter-sim/board)
Control channel on /tmp/sorter-sim/control.sock: python -m hardware.sim.ctl --control /tmp/sorter-sim/control.sock list
```

Options:

| Option | What it does |
|---|---|
| `--scenario NAME_OR_FILE` | The servos on the board's bus to start with: `four-doors` (default: IDs 1 to 4, stops at 150 and 850), `one-door`, `new-servos` (three, all ID 1), `empty`, or a JSON file (below) |
| `--speed X` | Run the world X times faster than real time |
| `--link PATH` | Keep a symlink to the board's terminal at PATH |
| `--adapter` | Also open a pretend USB servo adapter |
| `--adapter-scenario NAME_OR_FILE` | The adapter's servos (implies `--adapter`) |
| `--adapter-echo` | The adapter hears what it sends, as one with a shared transmit and receive line does |
| `--adapter-link PATH` | Keep a symlink to the adapter's terminal at PATH |
| `--control PATH` | The control socket (default `/tmp/sorter-sim/control.sock`) |

A scenario file (every key may be left out):

```json
{
  "speed": 1.0,
  "chute": {"start_angle": 120, "magnet_angle": 0, "magnet_width": 18, "gear_ratio": 6},
  "board_servos": [
    {"id": 1, "model": "SC15", "position": 500, "lower": 150, "upper": 850},
    {"id": 1, "model": "SC15", "position": 520, "lower": 150, "upper": 850, "label": "twin"}
  ],
  "adapter_servos": []
}
```

Positions and stops are in the servo's own counts (0 to 1023 for the SC
series). Models: `SC15`, `SC09`, `STS3215`.

## Change the world while it runs

```sh
uv run python -m hardware.sim.ctl list
```

Every servo has a label (`s1`, `s2`, ...; `list` shows them). Commands name a
servo by its label, or by its ID when only one servo has it.

| Command | What it does |
|---|---|
| `list` | The whole world as JSON: steppers, chute, hall sensor, outputs, servos |
| `plug --id N [--position P] [--lower L] [--upper U] [--model M] [--label NAME] [--bus adapter]` | Plug in a new servo |
| `plug LABEL` | Plug an unplugged servo back in |
| `unplug SERVO` | Unplug a servo: it falls silent |
| `turn SERVO POSITION` | Turn a door by hand. Refused while its torque is on: it holds |
| `block SERVO POSITION` | Put something in a door's way at POSITION |
| `unblock SERVO [POSITION]` | Take it out again (all blocks, or the one at POSITION) |
| `stops SERVO LOWER UPPER` | Move a door's hard stops |
| `servo-power off\|on [--bus adapter]` | Cut or restore the servos' power. Coming back, a servo has lost its torque and anything written to it while it was locked |
| `line stuck\|ok` | Hold the servo line low: the board answers "Servo bus line is stuck" |
| `hall active\|inactive\|auto` | Hold the hall sensor, or let the magnet decide |
| `magnet ANGLE [--width W]` | Move the magnet window |
| `chute-angle ANGLE` | Turn the chute by hand (its stepper's count does not change) |
| `board silent\|answer` | Make the board stop answering, and come back |
| `motor-power off\|on` | Cut the stepper drivers' power: their registers stop answering |
| `speed X` | Run the world faster or slower from now on |

The channel is a Unix socket taking one JSON object a line, for example
`{"cmd": "turn", "servo": "s2", "position": 300}`, and answering
`{"ok": true, "result": ...}` or `{"ok": false, "error": "..."}`.
`hardware.sim.control.request(path, payload)` sends one from Python.

## Run the backend against it

The backend finds a board on a plain serial port when it is named in
`SORTER_HEADER_UART`. It also needs a machine configuration and a state
database of its own, so it does not touch a real machine's:

```sh
cd software/sorter/backend
cp ../../machine.example.toml /tmp/sorter-sim/machine.toml
SORTER_HEADER_UART=/tmp/sorter-sim/board \
MACHINE_SPECIFIC_PARAMS_PATH=/tmp/sorter-sim/machine.toml \
LOCAL_STATE_DB_PATH=/tmp/sorter-sim/local_state.sqlite \
uv run python main.py
```

On macOS a pseudo-terminal accepts only the standard baud rates, and the
backend asks for 1.5 Mbps on a header UART. Name a standard rate after the
path: `SORTER_HEADER_UART=/tmp/sorter-sim/board:115200`. (The rate means
nothing to a pseudo-terminal; Linux takes any.)

The pretend adapter is opened the same way as a real one:

```python
from hardware.feetech.adapter_link import AdapterServoLink
link = AdapterServoLink("/tmp/sorter-sim/adapter")  # on macOS: baudrate=115200
```

## Where it differs from the real board

- Commands and servo transactions take no time on the pretend board; a missing
  servo costs nothing instead of 2 ms. The world moves in 1 ms steps (the
  firmware's motion update rate), so a homing stop lands within a microstep.
- StallGuard never trips: `GET_STALL_STATUS` is always 0 and `SG_RESULT` is a
  constant while a motor turns.
- Every TMC2209 register reads back what was written, even the ones a real chip
  cannot be read from (`IHOLD_IRUN`, `TCOOLTHRS`, `SGTHRS`, `COOLCONF`).
- `REBOOT_BOOTLOADER` gets no reply and changes nothing.
- The servos never set their own overload or temperature flags, ignore their
  PID, torque limit and return delay registers, read a steady 6.1 V, and do not
  turn their torque on when a goal is written. An SC goal's time and an STS
  goal's speed only slow a move.
- The EEPROM lock: a write to a saved register (below 40) takes effect at once,
  locked or not, and survives a power cut only if the lock was open.
- Two servos answering at once always garble each other here; on a real bus
  they nearly always do.
- One port: there is no separate USB and header link.
