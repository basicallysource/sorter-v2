# Operation 30 Hertz

Architectural benchmarks for the sorter's coordinator hot path.

The main sorter is single-threaded sequential coordinator + per-thread
inference + GIL-starved Python list comprehensions, capping us at ~0.6 Hz
of decision-making against a 30 Hz target.

This folder contains two minimal, faithful reproductions of the workload
shape (3 cameras + RKNN per-frame inference + MJPEG preview + bus-serialized
mock subsystem commands):

- `rev01/` — same architecture as the live code. Should reproduce the
  ~0.6 Hz bottleneck on the Pi.
- `rev02/` — restructured: each camera owns its own inference, each
  subsystem owns its own thread. Should hit ≥25 Hz on the same Pi.

Run results land in `results/` as JSON. See `tasks/operation-30hz/README.md`
in the agent-notes repo for the full plan and pass conditions.

## Run on the Pi

```
ssh root-spencer-01
cd /home/orangepi/sorter-v2-fresh/software/operation_30hz
# Required: sorter-backend-dev must be STOPPED (it holds the cameras).
# Use --duration to control how long each rev runs (default 20s).
python3 bench/run_rev.py rev01 --duration 20
python3 bench/run_rev.py rev02 --duration 20
python3 bench/compare.py results/rev01_*.json results/rev02_*.json
```
