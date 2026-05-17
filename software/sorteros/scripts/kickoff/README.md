# SorterOS Kickoff

Small web UI for kicking off an `extend.sh` build on Hive, watching its
progress, and streaming the resulting `.img` back to `~/Downloads/`.
Designed so a build survives random ssh hiccups: the browser tab is
just a viewer, the server holds state, and the actual build runs on
Hive under `nohup` regardless of whether the UI is open.

## Launch (manual)

Two ways. Pick whichever fits the situation.

### Foreground (terminal stays attached, Ctrl+C stops it)

```bash
cd software/sorteros/scripts/kickoff
./serve.sh
```

### Background (manage.sh — start/stop/status/logs)

```bash
./manage.sh start     # launch in background, writes pid → .pid, log → .serve.log
./manage.sh status    # is it up? on what URL?
./manage.sh logs      # tail -f the server log
./manage.sh stop      # graceful shutdown (SIGTERM, falls back to SIGKILL)
./manage.sh restart
```

`manage.sh` is what Claude uses to start/stop the service on your
behalf without holding a terminal. The pid file and log are
gitignored.

First run of either form takes ~10 s while `uv` materialises the venv.
Subsequent runs are instant. Open <http://127.0.0.1:8780/> in a browser.

No launchd, no plist, no auto-start at login. Manual only.

## What it does

1. SSHs to Hive (`$SORTEROS_BUILD_HOST`, default `45.55.232.164`) and
   runs `bash /basically/sorteros/build/extend.sh <flags>` under
   `nohup`. Hive picks up the auth key / branch defaults from
   `/basically/sorteros/build/.env`.
2. Tails `/basically/sorteros/out/extend.log` over SSH, parses stage
   markers (decompress → dd → parted → mkfs → chroot → apt → …), and
   pushes per-stage status to the browser via SSE.
3. When `image ready: <path>` appears in the log, kicks off
   `scp -C` to `~/Downloads/`. Progress bar tracks the local file
   size against the Hive image size.
4. Persists `STATE_FILE = .state.json` next to `server.py` so a
   server restart can resume the UI view of the most recent build.

## Form fields

- **Branch** — overrides `SORTER_BRANCH` from `.env` (passes
  `--branch` to extend.sh). Leave blank to use the `.env` value.
- **Input image** — `--in` for extend.sh; defaults to the v2.1
  `.img.zst`.
- **Output image name** — `--out` for extend.sh. The image filename
  drives the local download name.
- **Compress** — sets `--compress`. Adds ~30 min on a 2-vCPU host;
  off by default (raw `.img` is what we usually want).

## Environment

- `SORTEROS_BUILD_HOST` — Hive IP / hostname. Default
  `45.55.232.164`.
- `SORTEROS_BUILD_USER` — SSH user. Default `root`.

## Why this exists

Previous bringup loop relied on ad-hoc `nohup bash extend.sh` +
manual `scp` from another terminal. Random failures (ssh disconnects,
agent shells getting cleaned up, missed notifications) wasted ~10 min
per round trip. This wrapper:

- Persists state across the server restart, so reconnecting doesn't
  lose progress.
- Doesn't depend on the browser tab being open; the worker thread
  on the Mac keeps tailing.
- Surfaces *where* in the build pipeline we are, not just "running".

## Not in scope

- Auth on the local port. Bound to `127.0.0.1` only.
- Multi-build queueing. One build at a time.
- Killing a running build from the UI. To stop: ssh in and
  `pkill -f "bash extend.sh"` on Hive.
