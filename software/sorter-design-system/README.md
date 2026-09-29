# Sorter design system

How the Sorter's own web UI and Hive look, and how they are built: the
tokens, the components to copy, and the rules behind them, as a site that
shows each one working. It is the one place for this; the apps copy from
here.

```sh
pnpm install
pnpm dev
```

The site's pages:

- **Rules**: the ten things that hold the system together, each with the
  wrong way beside the right one.
- **Surfaces**: the planes a screen is built from (canvas, surface, well,
  raised) and which part owns each line.
- **Example app**: the Sorter UI's dashboard and settings, built from the
  components here.

Components are in `src/lib/components/`, the tokens (both modes) in
`src/app.css`, and the operator's primary color in `src/lib/theme.svelte.ts`.
