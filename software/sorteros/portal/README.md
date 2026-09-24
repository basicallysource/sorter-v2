# The setup page

What a phone sees after joining a Sorter's `SorterOS-Setup-XXXXXX` network:
the page that puts the Sorter on Wi-Fi. `sorteros-network` (in
`../build/overlay/usr/local/sbin/`) serves it and does the work; this folder
is only the page (SvelteKit, built to static files, baked into the image at
`/var/www/portal` by the builder's `portal` phase).

## How it works

The Sorter broadcasts its setup network on its own interface (`ap0`) while
its normal Wi-Fi (`wlan0`) stays free to scan and join. So a join from the
phone happens while the phone is still connected: the page asks, the Sorter
tries, and within seconds the page shows the result: the Sorter's address on
the network it joined, or why it couldn't join. Nothing restarts.

The page is driven by the Sorter's state, not by its own: every screen is
rendered from `GET /api/state`, so a reload, a phone that drops off and
rejoins, or a second phone all land on the same screen.

The page must work inside a phone's captive-portal window (iOS's sign-in
sheet, Android's "Sign in to network"), over plain HTTP, with no internet:
no fonts or scripts from anywhere else, no `window.open` or `target=_blank`,
no clipboard API or WebCrypto (both need HTTPS), and nothing that breaks
when the window is closed and reopened.

## API

All JSON. Times are Unix seconds on the Sorter's clock; `clock_ok` says
whether that clock has been set from the internet yet (before that, show no
times of day).

### `GET /api/state`

```jsonc
{
  "now": 1790274659,
  "clock_ok": true,
  "sorter": {
    "name": "sorter",                 // its hostname
    "mdns": "sorter.local",           // the name it answers to (sorter-2.local if taken)
    "software": {                     // first-boot install of the Sorter software
      "state": "waiting",             // waiting (for the internet) | installing | ready | failed
      "step": "Installing packages",  // human text, or null
      "done": 3, "total": 11          // steps
    }
  },
  "setup_network": {                  // null once it has closed
    "ssid": "SorterOS-Setup-ABCDEF",
    "live_join": true                 // false on a radio that must leave the air to join: the phone loses the page
  },
  "networks": [                       // every network the Sorter is on now
    { "kind": "wifi", "name": "HomeNet", "address": "192.168.1.68", "internet": true },
    { "kind": "ethernet", "name": "Ethernet", "address": "192.168.2.3", "internet": false }
  ],
  "cable": "none",                    // none | plugged (a cable with a link, no address yet) | connected
  "join": {                           // the last join the page or the setup site asked for, or null
    "ssid": "HomeNet",
    "state": "failed",                // joining | joined | failed
    "reason": "password",             // failed only: password | not_found | no_address | timeout | other
    "detail": "Secrets were required, but not provided",  // NetworkManager's words, for support
    "address": null,                  // joined only: its address on that network
    "internet": null,                 // joined only: whether the internet answers through it
    "source": "phone",                // phone | setup_site
    "at": 1790274600
  },
  "scan": {
    "scanning": false,
    "at": 1790274500,
    "networks": [
      { "ssid": "HomeNet", "signal": 77, "security": "WPA2", "saved": true }
    ]                                 // strongest first; security "" is open, "802.1X" is enterprise
  },
  "events": [                         // what the Sorter did, oldest first, the last 20
    { "at": 1790274440, "text": "Started" },
    { "at": 1790274460, "text": "Opened the setup network SorterOS-Setup-ABCDEF: no cable, no saved Wi-Fi" }
  ]
}
```

### `POST /api/join`

```jsonc
{ "ssid": "HomeNet", "password": "…", "hidden": false,
  "timezone": "America/New_York",     // the phone's, for the clock and the Wi-Fi country
  "name": "sorter-3",                 // optional: rename the Sorter
  "rendezvous_id": "…" }              // optional: a Find my sorter link to tell the address to
```

`202 {"ok": true}` and `join.state` becomes `joining`; poll `/api/state`
every second or two until it changes. `400 {"detail": "…"}` for a request
it can't try (no name, a password under 8 or over 63 characters, an
enterprise network), with the text to show.

### `POST /api/scan`

Starts a fresh scan (`202`); `scan.scanning` is true until it's done.

### `POST /api/done`

The person has what they need: the setup network closes a few seconds
later, and the phone goes back to its own Wi-Fi.

### Captive-portal checks

Every other path redirects to `/`, which is how phones notice the setup
page and open it by themselves.

## Working on the page

```sh
cd frontend
pnpm install
pnpm dev        # the dev server answers /api/* from fixtures; ?scenario=… picks one
pnpm build      # static files in build/, what the image serves
```

To serve a build the way the Sorter does, with a pretend network:

```sh
python3 ../build/overlay/usr/local/sbin/sorteros-network.py --mock --port 8090 --static-dir frontend/build
```
