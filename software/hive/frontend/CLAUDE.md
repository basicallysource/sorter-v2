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
| `warning-strong`, `warning-bg` | Readable amber ink + wash for warning copy (flips with the theme) |
| `warning-ink` | Amber ink for text on the *fixed* LEGO yellow (`bg-warning`); theme-independent |
| `canvas` | Near-black media backdrop for image/annotation viewers; theme-independent |

Use them via Tailwind utilities: `bg-primary`, `text-text-muted`, `border-border`, `bg-success/[0.06]`, etc.

### Dark mode

Dark mode is a `.dark` class on `<html>` (set by `src/app.html` + `src/routes/+layout.svelte`
from `$lib/stores/theme`), and `.dark` in `src/app.css` **re-points the `--color-*` variables**.
So a component is dark-mode-correct precisely when it uses the tokens: `bg-white` renders a white
card on a dark page, and any hex literal is frozen to whichever theme it was picked for.

Two tokens are deliberately theme-*independent* (`canvas`, `warning-ink`) because they sit on
content that does not flip — a photo, or the fixed LEGO yellow. Everything else flips.

**Do not** introduce raw `bg-[#...]` / `text-[#...]` / `border-[#...]` literals, and do not reach
for Tailwind's stock palette (`bg-white`, `text-black`, `bg-gray-950`, …) — none of it is
theme-aware. The only places where raw color values are allowed:
- The palette swatch section of `src/routes/styleguide/+page.svelte` — the swatches need
  the literal hex values for display. The component demos on the rest of that page use
  tokens like everything else, so the styleguide renders correctly in both themes.
- Data-viz palettes drawn over sample photos: `src/lib/components/sample/bbox-helpers.ts`,
  the annotator box palette, the model-compare palette, and the two untokenised midpoints of
  the coverage ramp in `Sparkline.svelte` / `DiversityDonut.svelte`. These are categorical,
  never sit on a themed surface, and have no token equivalent.
- Modal/overlay scrims (`bg-black/50`) and chips floating on a photo.
- Static assets / SVG / favicons.

## Favicons — one mark, a color per site

The ecosystem is several separate web UIs that people keep open side by side:
Hive, the docs site, and the machine's own UI. A tab strip full of identical
basically bricks tells you nothing, so **the mark is constant and the color
carries the identity**: the basically brick (black outline, white fill) on a
full-bleed colored disc.

| Site | Color | Palette token |
|---|---|---|
| Hive | `#D01012` — LEGO red | `--color-primary` |
| Docs | `#FFD500` — LEGO yellow | `--color-warning` |
| A machine (Sorter UI) | `#0055BF` — LEGO blue | `--color-info` |

These are the existing palette values, not new ones. **This is currently a
favicon-only convention** — it does not tint headers, chrome, or accents, and
nothing else in the app should read the "site color" yet. If that changes, the
system starts here.

The brick comes from `~/Documents/basically/logos/square zoomed.png`, the
outlined-and-white-filled version of the logo (transparent outside the brick).
Composite it, do not redraw it: building the mark from `basically-logo.svg`
means adding stroke weight to keep the lines alive at small sizes, and that
comes out visibly too bold. Crop to the alpha bbox, size the brick to 88% of
the disc radius (corner-to-center), center it, and render each output size at
its own resolution rather than downscaling one master.

Each site ships four files from its static dir:

- `favicon.ico` — 16/32/48 frames, the sizes browsers actually use in a tab.
- `favicon-96.png`, `favicon-192.png` — larger raster sizes.
- `apple-touch-icon.png` — 180×180, for iOS home-screen bookmarks.

Wire them up in `src/app.html`, not in a `<svelte:head>` — the icon is static
and belongs in the shell.

Adding a fourth site means picking a fourth color that is unmistakable from the
other three *at 16px*, where the brick is a smudge and the hue is the entire
signal. Check it at that size before committing to it. Do not restyle the brick
itself — a per-site mark defeats the point.

## Sharp edges (softer than Sorter)

Hive is a public community product, so it is permitted to be friendlier than the Sorter monitoring UI. Rounded corners are still restricted:

- Cards, panels, buttons, inputs, alerts, modals: **flat corners** (no `rounded-*`).
- Pill chips and avatar circles are OK (`rounded-full` on a small badge or avatar).

When in doubt, prefer flat. The divergence from the Sorter design language is intentional.

## Loading — `Spinner` is the only loading animation

`src/lib/components/Spinner.svelte` is a port of the canonical Sorter spinner
(`software/sorter/frontend/src/lib/components/Spinner.svelte`): four **sharp-cornered**
squares in a 2x2, one lit at a time, snapping clockwise every quarter cycle. The motion
is discrete (`linear`, not eased), it inherits color via `currentColor`, and it scales
via a `size` prop (a px number, default `16`). It deliberately keeps animating under
`prefers-reduced-motion` — a frozen indicator reads as a hung process.

This is the *one* exception to Hive's "friendlier than Sorter" license: spinners are
sharp-cornered, same as Sorter. There is no `rounded-full` here.

It is the **only** loading animation in the app. Import it and pass a `size`:

```svelte
import Spinner from '$lib/components/Spinner.svelte';
…
<Spinner size={32} />                       <!-- page/block loading -->
<Spinner size={12} class="text-text-muted" /> <!-- inline, next to a label -->
```

Never hand-roll a loading indicator: no `animate-spin`, no `border-current
border-t-transparent` ring, no spinning lucide `Loader2`, no inline `<svg
class="animate-spin">`, no CSS `@keyframes` rotation. `rg "animate-spin" src/` should
return nothing.

`Spinner` renders only the indicator — it does **not** center or pad itself. Wrap it
where you need layout (`<div class="flex justify-center p-8"><Spinner size={32} /></div>`).

Genuine skeleton loaders (content-shaped placeholder blocks) are a different thing and
are fine; this rule is about spinning/looping indicators.

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

Both must stay green. `rg "bg-\[#" src/` outside the styleguide's palette swatches should return ~nothing.
