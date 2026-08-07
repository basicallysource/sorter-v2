# Hive Frontend — Design System Rules

SvelteKit 2 + Svelte 5 + Tailwind v4. Package manager: pnpm.

## Tokens, not hex

Color tokens are defined in `src/app.css` via `@theme`:

| Token | Purpose |
|---|---|
| `primary`, `primary-hover`, `primary-light` | LEGO red + hover + pale tint |
| `bg`, `surface`, `border` | Neutrals (app bg, cards, dividers) |
| `text`, `text-muted` | Foreground |
| `danger`, `success`, `warning`, `info` | Status |

Use them via Tailwind utilities: `bg-primary`, `text-text-muted`, `border-border`, `bg-success/[0.06]`, etc.

**Do not** introduce raw `bg-[#...]` / `text-[#...]` / `border-[#...]` literals. The only places where raw hex is allowed:
- `src/routes/styleguide/+page.svelte` — the palette needs the literal values for display.
- `src/lib/components/Badge.svelte` — one legacy warm-yellow `#A16207` text; migrate if you touch it.
- Static assets / SVG / favicons.

## Sharp edges (softer than Sorter)

Hive is a public community product, so it is permitted to be friendlier than the Sorter monitoring UI. Rounded corners are still restricted:

- Cards, panels, buttons, inputs, alerts, modals: **flat corners** (no `rounded-*`).
- Pill chips and avatar circles are OK (`rounded-full` on a small badge or avatar).
- `Spinner` uses `rounded-full` because a circular spinner is the primitive.

When in doubt, prefer flat. The divergence from the Sorter design language is intentional.

## Primitives

Shared primitives live in `src/lib/components/primitives/` and are re-exported from the `index.ts` barrel:

```ts
import { Button, Alert, Tooltip } from '$lib/components/primitives';
```

- `Button` — variants `primary | secondary | danger | ghost`, sizes `sm | md`, supports `disabled`, `loading`, `type`, `onclick`.
- `Alert` — variants `success | warning | danger | info`, optional `title`, body via default snippet. No left-border accent stripe.
- `Tooltip` — hover + focus, placement `top | bottom | left | right`, body via default snippet.

Extend primitives rather than re-deriving their styles inline. If a one-off needs a new variant, add it to the primitive and showcase it in `src/routes/styleguide/+page.svelte`.

## Icons — always `lucide-svelte`, never hand-written SVG

`lucide-svelte` is a dependency. Every icon comes from it, imported per-icon so
the bundle stays small:

```svelte
import Pencil from 'lucide-svelte/icons/pencil';
…
<Pencil size={16} />
```

**Never paste an inline `<svg><path d="…">` into a component.** Hand-rolled path
data is unreviewable, renders at the wrong optical weight next to real icons, and
has repeatedly come out visually wrong. If Lucide doesn't have the icon, say so
rather than drawing one. Inline SVGs still present in older files are legacy —
replace them with the Lucide equivalent when you touch that markup.

## Verifying dev Hive — use Claude in Chrome

Dev Hive runs on this Mac (frontend [http://flux.tailf1686d.ts.net:5174](http://flux.tailf1686d.ts.net:5174)).
**Always verify Hive changes with the `mcp__claude-in-chrome__*` tools.** Every
interesting route is behind auth, so the browser the extension is connected to
has to be signed in as the agent account (`claude@sorterdev.com`, see
`sorter-v2-agent-notes/documentation/projects/hive/dev-hive.md`). Agents cannot
type passwords — if a route bounces to `/login`, say so and have Spencer sign
that browser in once; the session then persists for later sessions.

Do **not** use the Browser pane (`preview_start` / `mcp__Claude_Browser__*`) for
Hive: it has no session, so every authed route renders "Profile not found", and
it does not need its own dev server — one is already running on `:5174` with HMR,
so edits are live the moment they're saved. Do not build throwaway static HTML
mockups to eyeball a change; look at the real page.

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

Both must stay green. `rg "bg-\[#" src/` outside the styleguide should return ~nothing.
