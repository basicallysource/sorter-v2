# sorteros-setup

Browser-side .img customizer for SorterOS. SvelteKit + Tailwind, deployed
to Cloudflare Pages at **<https://setup.basically.website>**. Optional: a machine with
no settings uses Ethernet, or opens its setup network (`../portal/`).

## What it does

Pure client-side. No backend, no upload, no auth.

1. User drags in a `sorteros-v3-*.img` file.
2. File goes into a `Blob` in browser memory. Never uploaded.
3. User fills in: Wi-Fi SSID, password, hostname, optional SSH key.
4. JS searches the .img for the magic markers
   `__SORTEROS_CFG_START__` / `__SORTEROS_CFG_END__` (baked in by the
   image builder into `/etc/sorteros-config.toml`, padded to 4 KB).
5. JS overwrites that region with the user's TOML, padded back to the
   same byte length — ext4 metadata doesn't shift because file size
   doesn't change.
6. User clicks Download, gets the modified .img back instantly.

The Pi's `sorteros-firstboot` daemon reads `/etc/sorteros-config.toml`
on boot and applies it (NM connection, hostname, authorized_keys).

## Audience

Engineers who are not the terminal type. They can flash an SD card
(balenaEtcher) and they want their Wi-Fi credentials baked in before
flashing, without downloading a Mac app (signing/notarization headache)
or running a Python script. A web page works on any phone, any laptop,
any OS.

## Design rules — INHERIT THE SORTER FRONTEND

The site is brand-consistent with the sorter UI. **Before writing any
component, read `software/sorter/frontend/AGENTS.md` and apply the same
rules verbatim:**

- Sharp edges. No `rounded-*` utilities (exception: spinner).
- No left-accent borders. Flat 1px borders, all four sides, ~40% opacity.
- `text-sm` minimum for body copy. `text-xs` only for labels.
- No raw hex. All brand colors via `@theme` CSS variables.
- Use the Alert primitive for notifications, not hand-rolled borders.

The palette tokens live in
`software/sorter/frontend/src/routes/layout.css`. Copy them into this
project's `src/app.css` and keep them in sync (or extract into a shared
package later — not worth it yet, two sites).

## Stack

- **SvelteKit** (current major; pin to whatever the sorter frontend uses).
- **Tailwind v4** with `@theme` token approach.
- **`@sveltejs/adapter-static`**: no backend code, the whole site is
  prerendered to `build/`.

## Deployment

Cloudflare Pages project `sorteros-setup`, the same way `parts-calculator`
and `docs` ship: Cloudflare's GitHub integration builds
`software/sorteros/sorteros-setup` (`pnpm build`, output `build`) only when a
push touches this directory. A push to `main` is production at
setup.basically.website; any other branch gets a preview URL. There is
nothing to run by hand.

```bash
pnpm install
pnpm dev
```
