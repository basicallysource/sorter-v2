/**
 * The popover family. One engine (`floating.ts`), one look (`popover.css`),
 * three ways in:
 *
 *   Popover   — hover to peek, click to pin, arbitrary content and trigger.
 *   Anchored  — the same layer with no chrome, for a menu or a picker.
 *   use:tip   — a short label in place of a native `title`.
 *   use:tipScope — the same, for `data-tip` inside a block of `{@html}`.
 *
 * All three render into a layer at the end of the document rather than inside
 * the thing that opened them, which is what stops a scroll container clipping
 * them or a stacking context painting over them.
 *
 * These files are mirrored between `parts-calculator/src/lib/popover/` and
 * `docs/src/lib/popover/` and are checked for drift by
 * `scripts/check_popover_sync.py`. Change one, copy it to the other.
 */
export { default as Popover } from './Popover.svelte';
export { default as Anchored } from './Anchored.svelte';
export { tip, tipScope, type TipOptions, type TipParam } from './tip';
export type { Placement, Side, Align } from './floating';
