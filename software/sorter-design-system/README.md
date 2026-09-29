# Sorter design system

How the Sorter's own web UI, Hive and the SorterOS pages look, and how they
are built: the tokens, the components the apps copy, and the rules behind
them, as a site that shows each one working.

```sh
pnpm install
pnpm dev
```

The site has the rules (each with the wrong way beside the right one), the
foundations (surfaces, color, type, icons, layout), a page for each group of
components, an example app (the machine's dashboard and settings, built from
the components), and the written docs.

- `docs/` is the written system, one file per subject; start with
  `docs/README.md`.
- `src/app.css` holds every token, in both modes.
- `src/lib/components/` holds the components the apps copy unchanged.
