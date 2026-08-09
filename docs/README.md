# docs — the documentation site

The Sorter V2 documentation site: SvelteKit + Tailwind v4, fully prerendered
to static HTML (`@sveltejs/adapter-static`), with client-side navigation and
hover preloading between pages. It replaced the previous Jekyll site; the
content carried over unchanged.

## Run it

```bash
npm install
npm run dev        # dev server with HMR
npm run build      # static site → build/
npm run preview    # serve the built site
```

## How content works

Content is authored the same way it was under Jekyll:

- **Markdown + frontmatter** in `src/content/`. Same fields (`title`, `type`,
  `section`, `kicker`, `lede`, `author`, `parts_needed`, `tools_needed`, …).
  Per-section frontmatter defaults (formerly `_config.yml`) live in
  `src/lib/server/content.ts`.
- **Liquid still works.** Pages render through liquidjs at build time with
  `site.data.*`, `relative_url`, and the includes in `src/liquid/_includes/`
  (`step.html`, `harness/pin-swap.html`, …). Affiliate links and kramdown
  `{#heading-id}` attributes are expanded by small transforms in
  `content.ts`.
- **Data files** (`nav.yml`, `parts.yml`, `authors.yml`, `harness.yml`) live
  in `src/liquid/_data/` and drive the nav, parts cards, bylines, and the
  WireViz page.

Everything renders once at build time; the browser never fetches or parses
markdown. `src/routes/[...path]/+page.server.ts` prerenders one page per
content file (URLs match the old site's pretty permalinks).

See `AGENTS.md` for the authoring playbook (adding articles, images, parts,
authors).

## Styling

`src/routes/layout.css` — Tailwind v4 `@theme` tokens using the same naming
scheme as `software/sorter/frontend/src/routes/layout.css`, and the design
rules from that app's CLAUDE.md apply here too: sharp edges (no `rounded-*`),
flat 1px borders on callouts (no left-accent stripes), body copy ≥ 14px, no
raw hex in components. The docs keep LEGO red as `--color-primary`.
