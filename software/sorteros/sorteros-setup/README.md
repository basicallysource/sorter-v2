# sorteros-setup

Browser-side .img customizer for SorterOS v3. SvelteKit + Tailwind, deployed
to Vercel at **<https://setup.basically.website>**.

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
component, read `software/sorter/frontend/CLAUDE.md` and apply the same
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
- **`@sveltejs/adapter-vercel`** for deployment.
- No backend code. The whole site is static (SPA), so Vercel just serves
  the prerendered output.

## Bootstrap (one-time)

This directory is a placeholder. To turn it into a real SvelteKit project:

```bash
cd software/sorteros/v3/sorteros-setup
pnpm create svelte@latest .            # skeleton, TypeScript, no extras
pnpm install
pnpm add -D tailwindcss@next @tailwindcss/vite @sveltejs/adapter-vercel
```

Then:
1. Replace the default `+page.svelte` with the form scaffold below.
2. Copy `software/sorter/frontend/src/routes/layout.css` (the
   `@theme` block) into `src/app.css`.
3. Set `adapter: adapter()` in `svelte.config.js` to `adapter-vercel`.
4. Implement the byte-pattern patcher (see `src/lib/img-patch.ts`).

## Deployment

```bash
vercel link               # one-time, point at the "sorteros-setup" Vercel project
vercel --prod             # ship to setup.basically.website
```

Spencer has the Vercel project and domain set up. CI hookup is TBD; for
now, deploy by hand.

## Files in this scaffold

- `README.md` — this file.
- `package.json` — declares the deps to install via `pnpm install`.
- `svelte.config.js` — Vercel adapter wired up.
- `src/routes/+page.svelte` — the customizer UI.
- `src/lib/img-patch.ts` — the byte-pattern search/replace.
- `src/app.css` — Tailwind directives + theme tokens (placeholder).

Run `pnpm create svelte@latest .` *over the top* of this directory to
fill in the missing pieces (`vite.config.ts`, `tsconfig.json`,
`.gitignore`, etc.); the create script preserves files that already
exist.
