# Sorter design system

How the Sorter's own web UI (`software/sorter/frontend`), Hive
(`software/hive/frontend`) and the SorterOS pages look and are built: the
tokens, the components those apps copy, and the rules behind them, with a
site that shows each one working. This folder is the one place for it; the
apps' own AGENTS.md files point here.

Read `docs/README.md`, then `docs/rules.md`. `docs/apps.md` says what differs
in each site; `docs/decisions.md` has what was decided and when.

## Working in here

- **The system changes here first.** A component, a token or a rule that an
  app needs is added here, with its example on the site and its words in
  `docs/`, and the app copies the file again. Never fork a component inside an
  app.
- **Every rule has its words in `docs/`** and its example on the site. Change
  both together. The site's pages carry one line under each example; the
  rule's full text lives in `docs/`.
- **Components** are `src/lib/components/`, one file each, with a comment at
  the top saying what it is for and which doc covers it. Callback props, not
  `createEventDispatcher`. Tokens only in markup (`docs/color.md`).
- **The site's own pieces** are `src/lib/site/` and `src/routes/(site)/`; the
  example app is `src/routes/(app)/example/`. Neither is copied into an app.
- **A new look is chosen side by side.** When a part of the look is in
  question, draw the options on one page, each on the same sample, and let
  the choice be made there. The winner becomes the only value in `app.css`;
  the losing options and anything they needed are deleted, and
  `docs/decisions.md` records the choice.
- **Delete, don't preserve.** When a rule changes, the old one goes; the
  history is git.
- **Check after every visual change** as `docs/engineering.md` says: `pnpm
check` clean, the pages at 1440 and 390 in both modes, seams, overflow, the
  console, the keyboard.

## Running it

```sh
pnpm install
pnpm dev
```
