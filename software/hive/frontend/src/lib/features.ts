/**
 * Frontend feature flags.
 *
 * Single source of truth so we can hide / re-expose half-baked features
 * without scattering inline ``{#if false}`` checks. Flip a value here and
 * every gated surface follows.
 */

export const FEATURES = {
	/**
	 * Manual bounding-box editing on the sample detail page + the
	 * annotate-mode toggle in the review queue. The canvas works for
	 * drawing but the save → DB round-trip currently misbehaves on
	 * remount, so the entry points are hidden until that's solid.
	 * Existing boxes still render visually — only the edit controls
	 * are gone.
	 */
	ANNOTATION_EDITING: false
} as const;
