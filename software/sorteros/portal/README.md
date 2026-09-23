# SorterOS Captive Portal

The setup page a SorterOS machine serves on its `SorterOS-Setup-XXXXXX`
network. `sorteros-network` (in `../build/overlay/usr/local/sbin/`) starts it
at boot when the machine has no Ethernet and no saved Wi-Fi that works, and
stops it once the machine is online. The builder's `portal` phase bakes both
halves into the image.
Below is how to run it locally in mock mode, with no hardware.

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

When the connect endpoint is called, the backend:

1. writes `/etc/NetworkManager/system-connections/<SSID>.nmconnection`,
   remembering any profile it replaced
2. responds 200 to the frontend so the handoff page renders
3. waits 5 s, runs `nmcli connection up <SSID>` (30 s timeout); joining
   takes the radio from the setup network
4. on success: merges the network, hostname and SSH key into
   `/etc/sorteros-config.toml` (keeping anything the setup site put there,
   such as a Tailscale key), backs the profile up, removes the setup
   network profile and touches `/run/sorteros/portal-connected`, which
   `sorteros-network` is waiting for; firstboot applies the hostname and key
5. on failure: puts the replaced profile back (or removes the new one) and
   brings the setup network back up so the user can retry

Every API request touches `/run/sorteros/portal-activity`, so
`sorteros-network` never drops the setup network to retry saved networks
while someone is using the page.

| Switchover task  | flips `last_attempt=ok` | runs `nmcli connection up <SSID>`, signals |
| IP announce      | logs "would announce"   | reads wlan0 IP, encrypts, POSTs to Hive  |
| Hostname read    | local `gethostname()`   | local `gethostname()`                    |

## Not done yet (next PRs)

- **First-hardware-boot validation**: full end-to-end test on a fresh
  CM5 — flash → AP → smartphone captive-portal sheet → submit → handoff
  → firstboot stages → sorter-ui. Backend can be retuned (timeouts,
  switchover delay) based on what the real Wi-Fi chip does.
- **Tailscale auth in portal**: optional field so a fresh image joins
  the org tailnet without ever touching SSH first. Already plumbed in
  `/etc/sorteros-config.toml` by firstboot's `stage_tailscale_up` —
  just needs the input on the portal form.
- **Hardened captive-portal probe responses**: today every probe gets a
  302, which works but logs as "captive portal" forever.

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

## Re-announce safety net

The portal's immediate announce is the fast path, but it fires once from
a process that's killed seconds later. So the portal also persists the
rendezvous to `/var/lib/sorteros/ip-announce.json`
(`{rendezvous_id, public_key, hive_url, created_at}` — never the private
key), and **sorteros-firstboot re-posts the current LAN IP each loop**
until a 15-minute window elapses, then deletes the file.

This covers a failed first announce, a lookup page opened a little late,
and a DHCP renewal that changes the IP mid-onboarding. firstboot reads
the egress IP from a `connect()`-only UDP socket (works on wlan0 or
eth0), lazy-imports `cryptography`, and wraps every path so the
never-crash daemon contract holds. See `_maybe_reannounce_ip` in
`build/overlay/usr/local/sbin/sorteros-firstboot.py`.
