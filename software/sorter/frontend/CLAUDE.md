# Sorter frontend — design rules

The Sorter UI is a local, industrial monitoring tool. The style is deliberately
sharp-edged and dense. When adding or editing components, follow these rules.

## Sharp edges — no `rounded-*`

Do not use any Tailwind `rounded-*` utility, and do not set `border-radius` in
CSS. The only exceptions are:

- `src/lib/components/Spinner.svelte` — circular spinner uses `rounded-full`.
- `src/lib/components/MachineDropdown.svelte` — machine status dot uses
  `rounded-full`.

Any other rounded corner is a bug. The style guide at `/styleguide` is the
source of truth.

## No left-accent borders

Notifications, banners, and info/error boxes use a flat 1px border at ~40%
opacity on *all four sides*. Do not use `border-l-2`, `border-l-4`, or any
single-side colored stripe. The only exception is the servo-state indicator
inside `SetupServoOnboardingSection.svelte`, where a left stripe encodes
hardware servo state.

Use the `Alert` primitive (`$lib/components/primitives`) for anything
notification-shaped. Do not hand-roll `border border-*/40 bg-*/[0.06]` blocks.

## No raw hex colors

All brand colors live in `src/routes/layout.css` as `@theme` CSS variables.
Tailwind v4 auto-generates utilities for them: `bg-danger`, `text-success`,
`border-warning`, `bg-info`, `bg-primary-light`, etc. Dark variants live under
`text-*-dark` / `bg-*-dark`.

Do **not** write raw hex like `bg-[#D01012]` or `text-[#00852B]` in component
files. The only files allowed to reference raw hex for the brand palette are:

- `src/lib/lego-colors.ts` — the LEGO color dataset.
- `src/routes/styleguide/+page.svelte` — showcase of the raw palette.
- `src/lib/assets/*` — SVG assets.

Neutral off-brand tints (e.g. `#C9C7C0` dividers, `#1A1A1A` deep text,
`#FFD500` LEGO Yellow highlight) are allowed inline until a token is added.

## Use the primitives

Import buttons, inputs, alerts, and tooltips from
`$lib/components/primitives`:

```svelte
import { Button, Input, Alert, Tooltip } from '$lib/components/primitives';
```

- `Button` — `variant: primary | secondary | danger | ghost`, `size: sm | md`,
  supports `loading` (renders `Spinner` automatically) and `disabled`. Callback
  props only — no `createEventDispatcher`.
- `Input` — wraps the `.setup-control` class; `type: text | number | password |
  email | search`, `bind:value`, `onchange`, `oninput`.
- `Alert` — four variants `success | warning | danger | info`. Body via default
  snippet.
- `Tooltip` — hover/focus only, no portal. `text` prop plus trigger as default
  children.

New button or form surfaces should use these — don't add a new `.setup-button-*`
or `.input-*` class. Extend the primitive instead.
