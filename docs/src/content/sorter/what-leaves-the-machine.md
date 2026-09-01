---
layout: default
title: What leaves the machine
type: reference
section: sorter
slug: sorter-what-leaves-the-machine
audience: self-hosting operator
last_verified: 2026-07-13
kicker: Sorter — Under the hood
lede: Every network connection the backend can make, what each one carries, and which ones you can turn off.
permalink: /sorter/what-leaves-the-machine/
---

The machine sorts fully offline except for piece recognition. Everything below
is the complete list of outbound connections the backend can make — there is no
other background traffic. Two connections happen without any setup on your part
(piece recognition and the status ping); the rest only run once you configure
them.

## Brickognize — piece recognition (required)

During sorting, a cropped photo of each piece is sent to
`api.brickognize.com` to identify the part and color. This is the core
recognizer and there is currently no way to sort without it — no off switch.
The request carries the image and nothing else — no account, no machine
identifier.

## Status ping — on by default

Once an hour (and shortly after the backend starts), the machine sends a small
status report to `hive.basically.website` so we know how many machines exist,
whether they're online, what software they run, and roughly how much they sort.
It runs whether or not you've connected a Hive account.

To send it, the machine silently enrolls a **device identity** with
`hive.basically.website` the first time: a random key generated on the machine,
exchanged for a token. This is not an account and creates none — it only lets
the server keep one record per machine instead of trusting self-reported ids.
The report also carries a **random install ID** generated on the machine — that
ID is your handle for viewing and deleting the data (below). Neither is derived
from the machine's network details. We can tell one machine apart from another
and see the IP it connected from (which gives an approximate country/region,
the same as any web request).

**If you've registered a Hive account,** the ping additionally includes your
account machine IDs — the same IDs you already gave Hive when you registered —
so we can link this install to your account(s). This only happens once you've
voluntarily created an account and registered the machine; an unregistered
machine stays fully anonymous. Account tokens are never sent.

This is the complete payload — nothing else is collected:

| Field | Example | What it is |
|---|---|---|
| `install_id` | `a1b2…` random UUID | Anonymous per-install ID. Not your account. |
| `created_at` | 2026-07-13 | When this install first generated its ID (its "birthday"). |
| `reason` | `boot` / `periodic` | Whether this was a startup ping or the hourly one. |
| `software.version` | `sorter/canary/v0.1.0-29-g…` | Software version + release channel + commit. |
| `os` | `Debian … / SorterOS 1.x` | OS name and SorterOS image version, if present. |
| `hardware` | Orange Pi 5, 8 GB, 47 °C, disk free | Board model, RAM, CPU temperature, disk space. |
| `config` | `classification_channel` / `pulse_perception_rev01` / `two_piece_…` | Which machine setup and feeder / classification modes are running. |
| `usage` | pieces seen/classified/distributed, hours powered/sorted, best rate | Cumulative counters — "how much it sorts." |
| `uptime` | process + system seconds | How long the software and the machine have been up. |
| `registered` | `true` / `false` | Whether a Hive account is configured. |
| `machine_id`, `accounts` | UUIDs | **Only if registered:** your local machine ID and each account's machine ID, to link this install to your account(s). Never tokens. Absent on unregistered machines. |

What is **not** in it: no images, no per-piece records, no part numbers, no
account tokens, no serial numbers, MAC addresses, hostnames, or WiFi details.
Only what's in the table above.

**Turning it off:** set `SORTER_BASE_REPORTING_OFF=1` in the machine environment
and restart the backend. The report thread then never starts.

**Seeing exactly what your machine sends:** open `/telemetry` on the machine's
web UI (a hidden page — type the path). It shows your install ID, whether the
ping is on or off, and the exact JSON that would be sent.

**Deleting it:** copy your install ID from `/telemetry` and paste it into
[hive.basically.website/forget](https://hive.basically.website/forget). That
erases all status-report data tied to that ID. (Turning the ping off stops
future pings but doesn't delete what was already sent — use the form for that.)
We also age old records out on our side over time; the form is there if you
want it gone now.

## basically color model — off until you select it

In Settings → Tuning → Classification Providers you can switch color
prediction from Brickognize to the hosted color model at
`hive.basically.website`. With it selected, the same cropped piece photos that
go to Brickognize are also sent there (under the device identity above), and
**are stored on our side** along with the prediction — that's what trains the
next revision of the color model. Nothing else is sent: crops, camera channel
numbers, and the piece's internal id. Switch the provider back to Brickognize
and this traffic stops entirely.

## Hive — optional, off until you connect it

The machine makes **no** connection to Hive unless you add a Hive target
(URL + API token) in settings. Remove the target and all of the below stops.

With a target configured:

**Heartbeat** — every 30 seconds, a keep-alive so the UI can show whether
the server is reachable. The server records when your machine was last seen
and the IP it connected from. At most every 30 minutes the heartbeat also
carries the machine specs snapshot (see the Machine specs field below).

**Part dimension lookups** — when a piece is classified, the machine asks
Hive for that part's physical dimensions to route oversize pieces to the
bottom bin. This is a download; the only thing sent is the part number.

**Uploads** — each kind of upload is gated by a per-target toggle in the
Hive settings. A field that's off blocks the upload at send time, including
jobs already queued.

| Field | Default | What it carries |
|---|---|---|
| Detection images | on | Cropped pictures of individual pieces: live training samples and the per-piece image history. |
| Full camera frames | on | Uncropped camera captures and detection overlay images attached to training samples. |
| Piece metadata | on | Classification results per piece (part, color, confidence, bin, timestamps) and set sorting progress. |
| Channel crops (C2/C3) | off | Unlabeled bbox crops of pieces on the upstream feeder channels, tagged with position for same-piece lookup. Experimental, high volume. |
| Machine specs | on | Camera, controller board, platform and OS details, plus per-camera calibration state: whether a color profile is calibrated, whether it applies, its matrix and bias, and the saved device/orientation/capture settings. No image data. |

The field registry in `hive_telemetry.py` is the single choke point — no
other code path can upload to Hive, and adding a new kind of upload requires
adding a field to this list.

## Firmware update check — GitHub

Opening the firmware page fetches the release list from `api.github.com` to
show available firmware versions. Anonymous, standard GitHub API call. Only
happens when you use that page.

## BrickLink and OpenRouter — only with your own keys

If you configure your own BrickLink store credentials or an OpenRouter API
key, the machine calls those services for store inventory and experimental
detection features. Without keys, these paths never run.
