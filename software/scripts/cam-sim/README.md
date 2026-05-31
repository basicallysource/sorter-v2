# cam-sim

Simulated MJPEG camera streams for dev work without a powered machine.

## Why this exists

When iterating on the sorter software you often don't want the machine powered — no lighting, no moving parts, no powered USB hub for the webcams. This tool serves looping MJPEG streams over HTTP so the backend can connect to simulated cameras exactly as it would real ones. Swap integer device indices in `machine.toml` for the localhost URLs below and the backend never knows the difference.

## Setup

```bash
cp config.example.toml config.toml
# edit config.toml: point source_dir at wherever the machine stored sample images
uv run server.py
```

Each camera's `source_dir` is scanned recursively for `.jpg`/`.jpeg`/`.png` files, loaded into memory, and looped. The machine stores samples in two places:

- **Feeder cameras (c_channel_2, c_channel_3):** `software/logs/channel_zones/<run>/` — images named `*_ch2.png` / `*_ch3.png`
- **Classification channel:** `software/sorter/backend/blob/classification_training/<session>/captures/` — `*_top_full.jpg` files

If a `source_dir` doesn't exist or has no images, that camera serves a blank frame.

## Usage

```
uv run server.py                          # serve all cameras in config.toml
uv run server.py --config /other/path     # use a different config file
```

Startup output shows each camera's URL:

```
Starting cameras:
  c_channel_2               http://localhost:9002/  (device 2, 30.0 fps, 1280x720)
  c_channel_3               http://localhost:9003/  (device 4, 30.0 fps, 1280x720)
  classification_channel    http://localhost:9005/  (device 0, 30.0 fps, 3840x2160)
```

## machine.toml

Comment out the integer device entries and use these URLs instead:

```toml
[cameras]
# c_channel_2 = 2          # real device — comment out when using cam-sim
# c_channel_3 = 4
# classification_channel = 0
c_channel_2 = "http://localhost:9002/"
c_channel_3 = "http://localhost:9003/"
classification_channel = "http://localhost:9005/"
```

## Port map

| Role                   | URL                              |
|------------------------|----------------------------------|
| feeder                 | http://localhost:9000/           |
| carousel               | http://localhost:9001/           |
| c_channel_2            | http://localhost:9002/           |
| c_channel_3            | http://localhost:9003/           |
| classification_top     | http://localhost:9004/           |
| classification_channel | http://localhost:9005/           |

## Cached frames

Frames are stored in `frames/<role>/` (gitignored). Drop any JPEGs or PNGs there manually if you want to control exactly what each camera "sees". The server cycles through all files in the directory in sorted order.
