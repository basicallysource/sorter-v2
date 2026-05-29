# SorterOS Captive Portal

Zero-touch Wi-Fi onboarding for SorterOS images. Replaces the
`sorteros-setup/` Vercel customizer — the image ships generic, and the
user joins an AP on the device to configure Wi-Fi via a browser captive
portal.

Today this is a **spike**: backend + frontend run locally with no
hardware, no image-builder integration, no systemd unit. Once we're happy
with the UX we wire it into `build/overlay/` and add the AP-mode
orchestrator.

## Layout

```
portal/
├── README.md          # this file
├── backend/
│   ├── portal.py      # single-file FastAPI app (~400 LOC)
│   └── pyproject.toml # fastapi + uvicorn + pydantic
└── frontend/
    ├── package.json   # SvelteKit + adapter-static + Tailwind v4
    └── src/
        ├── lib/api.ts
        ├── lib/components/{SignalBars,HandoffPanel}.svelte
        └── routes/+page.svelte
```

## Run locally

Two terminals. Backend in mock mode (no `nmcli` calls):

```sh
cd backend
uv run --with fastapi --with uvicorn --with pydantic \
    python portal.py --mode mock --port 8088 --log-level info
```

Frontend with Vite dev (proxies `/api/*` to the backend on 8088):

```sh
cd frontend
pnpm install   # first time
pnpm dev
```

Open <http://localhost:5176>. You'll see a fake network list, can pick
one, the submit flow ends on the QR-code handoff screen.

To exercise the **production-style** build (static bundle served by the
backend directly, exactly how the image will work):

```sh
cd frontend && pnpm build
cd ../backend
uv run --with fastapi --with uvicorn --with pydantic \
    python portal.py --mode mock --port 8088 --static-dir ../frontend/build
```

Then hit <http://localhost:8088> — same UX, served from a single port,
identical to what the Orange Pi will do in AP mode.

## API contract

All routes the frontend uses:

| Method | Path               | Returns                                                                                |
| ------ | ------------------ | -------------------------------------------------------------------------------------- |
| GET    | `/api/status`      | `{ mode, hostname, suggested_url, configured, last_attempt }`                          |
| GET    | `/api/wifi-scan`   | `{ networks: [{ ssid, signal, security, in_use }], mocked }`                           |
| POST   | `/api/wifi-connect`| body `{ ssid, password?, hidden?, hostname?, sshKey?, rendezvousId?, publicKey? }` → `{ ok, next_url, hostname }` |

Captive-portal probe routes — all `302 → /` so the OS sheet pops the
portal automatically when the user joins the AP:

- `/hotspot-detect.html`, `/library/test/success.html` — iOS / macOS
- `/generate_204`, `/gen_204` — Android
- `/connecttest.txt`, `/ncsi.txt` — Windows
- `/canonical.html` — Firefox
- catch-all `/{anything}` — anything else still 302s

## Backend modes

```
--mode=auto   # ap if nmcli on PATH, else mock (default)
--mode=ap     # production on-device — real nmcli scan & connection writes
--mode=mock   # canned data, no system calls, safe for laptop dev
```

In `ap` mode `_nmcli_write_wifi` mirrors the format firstboot's existing
`stage_apply_config_toml` expects — same `.nmconnection` file shape so
the handoff to firstboot doesn't need any new logic.

When the connect endpoint succeeds, the backend:

1. writes `/etc/NetworkManager/system-connections/<SSID>.nmconnection`
2. writes `/etc/sorteros-config.toml` if the user provided a hostname or
   SSH key (same file firstboot already reads)
3. responds 200 to the frontend so the handoff page renders
4. waits 5 s, runs `nmcli connection up <SSID>` (30 s timeout)
5. on Layer-3 success: **announces the LAN IP** (see below), then touches
   `/var/lib/sorteros/wifi-configured` (firstboot's gate file) and drops
   the AP profile
6. on failure: leaves the AP up so the user can retry with a fresh
   password

The announce happens *before* the gate file is touched on purpose — the
onboarding orchestrator kills the portal process the moment the gate
appears, so the encrypted IP drop has to finish (or time out) first.

If the user cuts power between steps 1–6, firstboot at next boot will
still re-trigger the portal because the gate file is the last thing
written.

## Encrypted LAN-IP rendezvous

The hard part of headless onboarding is "what IP did my Pi get?". mDNS
(`.local`) covers Apple but is flaky on Windows / locked-down networks,
and the public NAT IP a server would see is useless for a LAN address.
So the Pi tells the user its LAN IP through Hive as a **zero-knowledge
dead-drop**:

```
browser (AP page)                 Pi (portal)                Hive
─────────────────                 ───────────                ────
generate RSA-OAEP keypair
+ random rendezvous id
        │ pubkey + id (wifi-connect POST)
        ├──────────────────────────▶ store
        │                            connect to Wi-Fi, read LAN IP
        │                            encrypt {ip,hostname,port} w/ pubkey
        │                            POST ciphertext ───────────▶ /api/machine-ip-lookup/<id>
   navigate to Hive lookup
   (privkey in URL #fragment)
   poll GET <id> ◀───────────────────────────────────────────── ciphertext
   decrypt w/ privkey → show "http://192.168.1.42/"
```

- Hive only ever stores **opaque ciphertext** — it never sees the LAN IP
  in clear. The Hive endpoints (`app/routers/machine_lookup.py`) are an
  in-memory, 10-minute-TTL, rate-limited dead-drop keyed by an
  unguessable id.
- The private key never crosses an origin boundary via storage —
  localStorage/cookies are origin-scoped and wouldn't survive the jump
  from `http://10.42.0.1` to `https://hive.basically.website`. It rides
  in the **URL fragment** (`#k=…`), which never reaches the Hive server.
- The lookup page is `hive.basically.website/machine-ip-lookup` —
  unlisted (not in nav), login-free, `ssr=false`.
- A malicious POST to a guessed id just stores junk that fails to
  decrypt in the browser; the page ignores undecryptable payloads.
- Crypto: RSA-OAEP-SHA256, 2048-bit. Browser uses WebCrypto, the Pi uses
  `cryptography`. Ciphertext is ~344 base64 chars.

The announce is **best-effort**: bounded retries over ~30 s, then
onboarding completes regardless. The `.local` address remains the
fallback and is still shown on the handoff screen.

## What's mocked vs. real

| Path             | mock mode               | ap mode                                  |
| ---------------- | ----------------------- | ---------------------------------------- |
| Scan             | canned 5-entry list     | `nmcli dev wifi list --rescan yes`       |
| Connection write | no-op                   | writes `.nmconnection` + `nmcli reload`  |
| Switchover task  | flips `last_attempt=ok` | runs `nmcli connection up <SSID>`, gates |
| IP announce      | logs "would announce"   | reads wlan0 IP, encrypts, POSTs to Hive  |
| Hostname read    | local `gethostname()`   | local `gethostname()`                    |

## Not done yet (next PRs)

- **First-hardware-boot validation**: full end-to-end test on a fresh
  CM5 — flash → AP → smartphone captive-portal sheet → submit → handoff
  → firstboot stages → sorter-ui. Backend can be retuned (timeouts,
  switchover delay) based on what the real Wi-Fi chip does.
- **Reset-GPIO / factory-reset**: long-press handler that deletes
  `/var/lib/sorteros/wifi-configured` and reboots so the device falls
  back into AP mode without re-flashing.
- **Tailscale auth in portal**: optional field so a fresh image joins
  the org tailnet without ever touching SSH first. Already plumbed in
  `/etc/sorteros-config.toml` by firstboot's `stage_tailscale_up` —
  just needs the input on the portal form.
- **Hardened captive-portal probe responses**: today every probe gets a
  302, which works but logs as "captive portal" forever. A friendlier
  exit experience is to flip the probes to "success" responses once
  `wifi-configured` exists so devices on the AP don't get stuck loops.

## Handoff screen

The handoff screen's primary action is **Find my sorter →**, a link (and
QR) to the Hive rendezvous page carrying the private key in its fragment.
On the same phone the user just taps it after rejoining their Wi-Fi; the
QR is for hopping to another device. The `.local` address is shown as the
secondary path for Apple devices and as a fallback when WebCrypto wasn't
available (e.g. a plain-http origin that isn't `localhost`).

mDNS lookup works natively on iOS and macOS; modern Chrome/Edge on
Android resolve `.local` via Network Service Discovery; on Windows the
user typically needs Bonjour. The Hive rendezvous exists precisely to
cover the networks where `.local` doesn't resolve.

## Re-announce hardening (future)

Today the announce only fires once, from the portal process, right after
connect. The Hive entry then lives for its 10-minute TTL, so a user who
opens the lookup page late within that window still gets the IP. The gap
is a first-announce that fails *and* never retries past the portal's
lifetime. A follow-up persists `{id, pubkey}` to disk and adds a
firstboot stage that re-announces the current IP each loop for the first
few minutes — covering DHCP renewals and transient Hive outages.
