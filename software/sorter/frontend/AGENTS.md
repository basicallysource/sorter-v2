# Sorter frontend

The machine's own web UI: a local, industrial monitoring tool, sharp-edged and
dense.

## How it looks

How this app looks and is built: `software/sorter-design-system` (read its
`AGENTS.md` and `docs/rules.md` first, and `docs/apps.md` for what differs
here). Components are copied from its `src/lib/components/` unchanged; a change
is made there first.

## Static files, no server

The UI ships as static files (`adapter-static`, SSR off in
`src/routes/+layout.ts`) that the backend's supervisor serves on port 80
(`software/sorter/backend/supervisor.py`); a machine runs no Node process. So
there are no `+server.ts`, `+page.server.ts`, `+layout.server.ts` or
`hooks.server.ts` files, and load functions run in the browser. Anything that
needs a server belongs in the backend. `pnpm dev` (port 5173) is for working
on the UI.
