# Hive frontend

SvelteKit 2 + Svelte 5 + Tailwind v4. Package manager: pnpm.

## How it looks

How this app looks and is built: `software/sorter-design-system` (read its
`AGENTS.md` and `docs/rules.md` first, and `docs/apps.md` for what differs
here). Components are copied from its `src/lib/components/` unchanged; a change
is made there first.

## Verifying a change

Look at the real page. Do not build throwaway static HTML mockups to eyeball a
change, and do not stand up a second dev server if one is already serving the
frontend with HMR.

Every interesting route is behind auth, so a browser with no session renders
"Profile not found" on all of them; verifying a change means driving a browser
that is already signed in. Agents cannot type passwords — if a route bounces to
`/login`, say so rather than trying to authenticate. Which browser, which
account and which host are properties of the machine you are running on, not of
this repo; they are recorded with the rest of the dev-environment notes.

## Svelte 5 conventions

- Props: `let { foo, onclose }: Props = $props();`
- State: `$state`, `$derived`, `$effect`.
- Slots: `Snippet` prop + `{@render children()}`.
- Events: **callback props** (`onclose`, `onclick`, `onsubmit`, …), not `createEventDispatcher` + `$bindable`. See `Modal.svelte` as the reference.

## Validation

```sh
pnpm --dir software/hive/frontend check
pnpm --dir software/hive/frontend build
```

Both must stay green. `rg "bg-\[#" src/` should find only the raw colors the
design system's `docs/apps.md` lists for Hive.
