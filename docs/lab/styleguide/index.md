---
layout: default
title: Styleguide
section: lab
slug: styleguide
kicker: Lab — Contributor Reference
lede: The shared visual language used by the Sorter UI, the SortHive community platform, and this documentation site. This page is the source of truth — both apps render an in-app `/styleguide` route that mirrors these patterns as a live smoke test.
permalink: /lab/styleguide/
---

## Design Principles {#design-principles}

Five rules that apply across Sorter, SortHive, and these docs. Every new screen or component must honor them unless you have a documented reason not to.

### 1. No rounded corners

Sharp 0px edges everywhere. The LEGO family is intentionally industrial — rounded corners belong to consumer surfaces, not to our tools. The only sanctioned exception is the circular check icon used in hero celebration panels.

### 2. No colored left-accent borders

Notifications and callouts use a flat 1px border at 40% opacity on *all four sides* — never `border-left: 4px solid` stripes. That style is forbidden by the style guide.

### 3. One unified notification template

Info, success, warning, and error notifications all share the same shape and rhythm; only the brand color tone changes. Never invent a fifth variant. See [Notifications](#notifications) below for the canonical markup.

### 4. 11px uppercase labels for micro-headings

Section labels, notification kickers, and stat cells use `11px` / `font-semibold` / `uppercase` / `tracking-wider`. Body copy stays at `12px` (`text-xs`) with relaxed leading. Resist the urge to grow labels back to `text-sm`.

### 5. Darker tones on tinted backgrounds

The standard LEGO palette is too light against the ~6% tinted notification backgrounds. Use the darker contrast tones listed in [Colors](#colors) for any text layered on a tinted surface.

## Colors {#colors}

### Brand colors — user-selectable primary

Each operator can choose their preferred LEGO primary in the app settings. The four primary options below are equally valid; every screen that uses a primary color must pull it from the `--color-primary` CSS variable rather than hard-coding one of the four values.

<div class="sg-swatch-grid">
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#D01012"></div>
    <div class="sg-swatch-label">LEGO Red</div>
    <div class="sg-swatch-value">#D01012</div>
    <div class="sg-swatch-usage">Default primary for SortHive and docs. Destructive actions, active nav, errors.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#0055BF"></div>
    <div class="sg-swatch-label">LEGO Blue</div>
    <div class="sg-swatch-value">#0055BF</div>
    <div class="sg-swatch-usage">Default primary for the Sorter UI. Info, focus rings, selection.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#00852B"></div>
    <div class="sg-swatch-label">LEGO Green</div>
    <div class="sg-swatch-value">#00852B</div>
    <div class="sg-swatch-usage">Success, completion, connected state, confirm buttons.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#FFD500"></div>
    <div class="sg-swatch-label">LEGO Yellow</div>
    <div class="sg-swatch-value">#FFD500</div>
    <div class="sg-swatch-usage">Warnings, calibration-weak, highlight. The canonical warning tone.</div>
  </div>
</div>

See [Primary Color](#primary-color) for the mechanics of how the pick is wired through the CSS variable.

### Dark contrast tones

Use these darker shades for any label text that sits on a tinted notification background. They are *not* replacements for the brand colors — they are strictly reserved for legibility on top of 6%-opacity surfaces.

<div class="sg-swatch-grid">
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#7A0A0B"></div>
    <div class="sg-swatch-label">Red (dark)</div>
    <div class="sg-swatch-value">#5C0708 / #7A0A0B</div>
    <div class="sg-swatch-usage">Notification labels on tinted red background.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#003A8C"></div>
    <div class="sg-swatch-label">Blue (dark)</div>
    <div class="sg-swatch-value">#003A8C</div>
    <div class="sg-swatch-usage">Notification labels on tinted blue background.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#003D14"></div>
    <div class="sg-swatch-label">Green (dark)</div>
    <div class="sg-swatch-value">#003D14</div>
    <div class="sg-swatch-usage">Notification labels on tinted green background.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#4A3300"></div>
    <div class="sg-swatch-label">Yellow (dark)</div>
    <div class="sg-swatch-value">#4A3300</div>
    <div class="sg-swatch-usage">Notification labels on tinted yellow background.</div>
  </div>
</div>

### Neutral tokens

The app-agnostic neutral palette. Every LEGO-family surface draws from these.

<div class="sg-swatch-grid">
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#F7F6F3; border-color:#E2E0DB"></div>
    <div class="sg-swatch-label">bg</div>
    <div class="sg-swatch-value">#F7F6F3</div>
    <div class="sg-swatch-usage">Page background.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#FFFFFF; border-color:#E2E0DB"></div>
    <div class="sg-swatch-label">surface</div>
    <div class="sg-swatch-value">#FFFFFF</div>
    <div class="sg-swatch-usage">Card and panel background.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#E2E0DB; border-color:#C8C6C1"></div>
    <div class="sg-swatch-label">border</div>
    <div class="sg-swatch-value">#E2E0DB</div>
    <div class="sg-swatch-usage">Divider lines, card outlines.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#1A1A1A"></div>
    <div class="sg-swatch-label">text</div>
    <div class="sg-swatch-value">#1A1A1A</div>
    <div class="sg-swatch-usage">Primary copy.</div>
  </div>
  <div class="sg-swatch">
    <div class="sg-swatch-chip" style="background:#7A7770"></div>
    <div class="sg-swatch-label">text-muted</div>
    <div class="sg-swatch-value">#7A7770</div>
    <div class="sg-swatch-usage">Secondary copy, labels, descriptions.</div>
  </div>
</div>

## Typography {#typography}

Both apps and these docs use IBM Plex Sans for copy and IBM Plex Mono for identifiers, URLs, hex values, and numeric read-outs.

### Type scale

| Role | Size | Weight | Classes |
| --- | --- | --- | --- |
| Page hero headline | 24px | Bold | `text-2xl font-bold text-text` |
| Section card title | 16px | Semibold | `text-base font-semibold text-text` |
| Section description | 14px | Regular | `text-sm text-text-muted` |
| Body / notification copy | 12px | Regular | `text-xs leading-relaxed text-text` |
| Micro-heading / stat label | 11px | Semibold | `text-[11px] font-semibold tracking-wider uppercase` |
| Identifier / URL | 14px | Regular | `font-mono text-sm text-text` |

### Rules of thumb

- **Never grow a micro-heading back to `text-sm`.** The 11px uppercase label is a deliberate rhythm — inflating it to the body scale dissolves the hierarchy we rely on inside notification blocks and stat cells.
- **Body copy is 12px (`text-xs`), not 14px.** Sorter and SortHive both default to the tighter scale; `text-sm` is reserved for hero descriptions and form labels that carry a specific hint.
- **Mono is for things you copy.** Hashes, URLs, hex codes, machine identifiers. Prose and UI chrome stay in IBM Plex Sans.

## Notifications {#notifications}

Every info, success, warning, and error surface must use the same template. Four variants, one shape.

### Shape contract

All four variants share the exact same layout:

- 1px border at 40% opacity on all four sides
- Background tint at ~6% opacity of the same brand color
- 11px uppercase kicker in the darker contrast tone
- 12px body text in the default `text-text` color
- No left-colored stripe, no rounded corners, no drop shadow

### Info (blue)

```html
<div class="border border-[#0055BF]/40 bg-[#0055BF]/[0.06] px-3 py-2
            dark:border-sky-500/40 dark:bg-sky-500/[0.08]">
  <div class="text-[11px] font-semibold tracking-wider text-[#003A8C]
              uppercase dark:text-sky-200">
    Calibration hint
  </div>
  <div class="mt-1 text-xs leading-relaxed text-text">
    Hold a flat reference card under the camera and click Capture.
  </div>
</div>
```

### Success (green)

```html
<div class="border border-[#00852B]/40 bg-[#00852B]/[0.06] px-3 py-2
            dark:border-emerald-500/40 dark:bg-emerald-500/[0.08]">
  <div class="text-[11px] font-semibold tracking-wider text-[#003D14]
              uppercase dark:text-emerald-200">
    Calibration is usable
  </div>
  <div class="mt-1 text-xs leading-relaxed text-text">
    White balance and exposure are within tolerance.
  </div>
</div>
```

### Warning (yellow)

The canonical warning tone is `#FFD500` — the real LEGO yellow. The yellow tint uses 10% opacity (not 6%) because yellow reads too faintly at the lower level.

```html
<div class="border border-[#FFD500]/50 bg-[#FFD500]/[0.10] px-3 py-2
            dark:border-amber-500/40 dark:bg-amber-500/[0.08]">
  <div class="text-[11px] font-semibold tracking-wider text-[#4A3300]
              uppercase dark:text-amber-200">
    Calibration weak
  </div>
  <div class="mt-1 text-xs leading-relaxed text-text">
    Reference patches drifted by 8.3 ΔE. Re-shoot the calibration card.
  </div>
</div>
```

### Error (red)

```html
<div class="border border-[#D01012]/40 bg-[#D01012]/[0.06] px-3 py-2
            dark:border-rose-500/40 dark:bg-rose-500/[0.08]">
  <div class="text-[11px] font-semibold tracking-wider text-[#5C0708]
              uppercase dark:text-rose-200">
    Connection failed
  </div>
  <div class="mt-1 text-xs leading-relaxed text-text">
    Could not reach the SortHive server. Check your credentials.
  </div>
</div>
```

### Why the uniform shape

Notification style drift was the single biggest source of visual noise before this rule existed. Keeping one template means:

- the eye instantly recognizes "this is a status message", regardless of tone;
- severity reads from *color*, not from *layout*;
- new contributors don't need to invent a new banner shape for every feature.

If you need a fifth visual affordance, you probably want a [panel or card](#components) instead of a notification.

## Components {#components}

Panels, buttons, form controls, and loading states — the building blocks that show up on almost every screen.

### Panels and cards

The base surface is a flat 1px bordered rectangle with the `bg-surface` background — called `.setup-panel` in the Sorter UI. Use it for grouped content, stat cells, and inline forms.

```html
<div class="setup-panel px-4 py-3">
  ... content ...
</div>
```

A hero panel (Setup Complete, first-run celebration, empty state) uses a gradient tinted background in the chosen accent color and may contain the single sanctioned rounded shape — the circular success check.

### Buttons

Three button roles:

- **Primary** — uses `--color-primary` (user-selected). One primary per screen, maximum.
- **Secondary** — flat bordered button with the neutral surface background.
- **Brand confirm** — inline affirmative actions that carry a fixed brand color regardless of the user's primary (for example, the LEGO-green "Connect to SortHive" confirm in the setup wizard).

```html
<!-- primary -->
<button class="setup-button-primary inline-flex items-center gap-2
               px-4 py-2 text-sm font-medium">
  Continue
</button>

<!-- secondary -->
<button class="setup-button-secondary inline-flex items-center gap-2
               px-3 py-2 text-sm text-text">
  Rescan
</button>

<!-- brand confirm -->
<button class="inline-flex items-center gap-2 border border-[#00852B]
               bg-[#00852B] px-4 py-2 text-sm font-medium text-white
               hover:bg-[#00852B]/90">
  Connect to SortHive
</button>
```

### Form controls

The `.setup-control` class gives every input the same focus ring and surface. Focus always draws from `--color-primary`, not a hard-coded brand color.

```html
<input type="text"
       class="setup-control w-full px-3 py-2 text-sm text-text"
       placeholder="e.g. Sorting Bench A">
```

### Loading states

The standard spinner row used when fetching async data inside a step or panel:

```html
<div class="setup-panel flex items-center gap-2 px-4 py-3
            text-sm text-text-muted">
  <Loader2 size={14} class="animate-spin" />
  Checking current SortHive configuration…
</div>
```

## Primary Color {#primary-color}

How the user-selectable primary is wired through CSS custom properties, and which semantic slots stay fixed regardless of the user's pick.

### Mechanics

- Each app reads `--color-primary` from CSS custom properties at the `:root` level.
- Defaults are:
  - **Sorter UI** → `#0055BF` (LEGO Blue)
  - **SortHive** → `#D01012` (LEGO Red)
  - **Docs site** → `#D01012` (LEGO Red)
- In both apps the user can override the default via **Settings → Appearance → Primary color**. The choice is persisted per-machine (Sorter) or per-user (SortHive).
- Components must consume `--color-primary` via the utility classes `.text-primary`, `.bg-primary`, `.border-primary`, or raw `var(--color-primary)` — **never via hard-coded hex values** of the four LEGO options.

### Semantic slots are fixed

Semantic slots are *not* affected by the primary picker:

- **Success** stays green (`#00852B`)
- **Warning** stays yellow (`#FFD500`)
- **Error** stays red (`#D01012`)
- **Info** stays blue (`#0055BF`)

This holds regardless of what the user picks as their primary.

### Collision handling

If a user picks a primary that collides with a semantic slot (for example, Green-as-primary on a success screen), the semantic slot wins on its own component and the primary slot uses its natural color everywhere else. The two rarely sit side by side, but when they do the semantic meaning takes precedence over the personalization.

### Checklist when adding a primary-coloured element

1. Use `var(--color-primary)` or one of the `.text-primary` / `.bg-primary` / `.border-primary` utility classes.
2. Don't hard-code `#0055BF`, `#D01012`, `#00852B`, or `#FFD500` for a primary slot.
3. Make sure the background and text pair still reach AA contrast when the user picks any of the four options — Yellow primary in particular needs dark text.
4. If the component has a focus ring, derive it from `--color-primary` too.

## Where this guide lives {#where-this-guide-lives}

- **Canonical prose and rules:** this page.
- **Live smoke test:** `/styleguide` in the Sorter UI and `/styleguide` in the SortHive frontend. Both routes render the same patterns with real components so designers can spot drift at a glance.
- **Design tokens:** `--color-bg`, `--color-surface`, `--color-border`, `--color-text`, `--color-text-muted`, `--color-primary` (CSS custom properties, same names across all three surfaces).

When you add a new pattern, update the matching section above first, then mirror it into both in-app styleguides.
