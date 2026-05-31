# sorteros-build-dashboard

Local Mac service for managing SorterOS image builds. Replaces manually tailing colima logs.

## What it does

- **Build dashboard** — live phase progress, ETA, streaming log, history of past `.img` files with Finder links
- **Build API** — agents and scripts can trigger builds and stream progress over HTTP without opening a browser
- **Preset config** — save your Wi-Fi/SSH/Tailscale credentials once; they auto-fill internal test builds so you can skip the on-device captive portal

Production images don't need a preset — they ship generic and configure themselves via the SorterOS captive portal on first boot. The preset is only for development convenience.

## Start

```bash
cd software/sorteros/build-dashboard
uv run python server.py
```

Opens at **http://localhost:7373**.

Requires colima running with the sorter-v2-03 repo mounted:
```bash
colima start --arch aarch64 --cpu 4 --memory 8 --disk 60 \
    --mount /Users/spencer/Documents/GitHub/sorter-v2-03:w \
    --mount /Users/spencer/Downloads:r
```

## Using from a browser

1. Fill in version/branch/base image (leave blank to use `config.toml` defaults and auto-discover the base image)
2. Select a preset config if you want credentials baked into the image
3. Click **Build image** — live log streams in the dashboard

## Using from an agent (HTTP API)

```bash
# Start a build
curl -X POST http://localhost:7373/build \
  -H 'Content-Type: application/json' \
  -d '{"version": "3.4.5", "branch": "sorteros-v3"}'

# Poll status
curl http://localhost:7373/build/status

# Stream logs (SSE)
curl -N http://localhost:7373/stream

# List past builds
curl http://localhost:7373/builds

# Open latest output in Finder
curl "http://localhost:7373/open-finder?path=/path/to/sorteros-v3.4.3-2026-05-19.img"
```

### SSE event types

| type | payload | description |
|------|---------|-------------|
| `state` | `{status}` | full status snapshot on connect |
| `log` | `{line, phase}` | one log line from the build |
| `start` | `{version}` | build just started |
| `done` | `{success, path}` | build finished |

## Preset config

`preset.toml` lives in this directory and is gitignored. Format mirrors `/etc/sorteros-config.toml`:

```toml
hostname = "sorterr"

[wifi]
ssid = "MyNetwork"
password = "secret"

[ssh]
authorized_key = "ssh-rsa AAAA..."

[tailscale]
auth_key = "tskey-auth-..."
tags = "tag:sorter"
```

In the **New build** form, choose "Use saved preset" to embed it in the next image. The dashboard saves the preset in-place; it does not trigger a build.

You can also paste preset TOML directly in the "Enter custom config" option for a one-off override.

## Port

Default port is `7373`. Override with `DASHBOARD_PORT=XXXX uv run python server.py`.
