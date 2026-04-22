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
