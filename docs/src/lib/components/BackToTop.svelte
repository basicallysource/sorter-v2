<script lang="ts">
	/* A floating "back to top" control, bottom right, on every page.

	   It is not permanently on screen: the assembly tree gets deep, and the
	   moment you want the menu again is the moment you start scrolling back
	   up. So it appears on an upward scroll once you are a screenful or so
	   down, and gets out of the way again as soon as you scroll on down. */

	// How far down the page you have to be before the button can appear.
	const SHOW_AFTER = 600;
	// Ignore scroll jitter and touch momentum wobble; only a deliberate
	// movement flips the direction. Small deltas accumulate instead of
	// resetting the anchor, so a slow drag upward still counts.
	const DELTA = 24;

	let visible = $state(false);
	let anchorY = 0;

	$effect(() => {
		anchorY = window.scrollY;

		const onScroll = () => {
			const y = window.scrollY;
			if (y < SHOW_AFTER) {
				visible = false;
				anchorY = y;
				return;
			}
			const delta = y - anchorY;
			if (delta <= -DELTA) {
				visible = true;
				anchorY = y;
			} else if (delta >= DELTA) {
				visible = false;
				anchorY = y;
			}
		};

		window.addEventListener('scroll', onScroll, { passive: true });
		return () => window.removeEventListener('scroll', onScroll);
	});

	function toTop() {
		const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
		visible = false;
		// The button is about to hide itself, so hand focus to the first thing
		// at the top of the page rather than dropping it on the body.
		document.querySelector<HTMLElement>('.site-header .brand')?.focus({ preventScroll: true });
	}
</script>

<button
	type="button"
	class="back-to-top"
	class:is-visible={visible}
	aria-label="Back to top"
	title="Back to top"
	onclick={toTop}
>
	<svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="14" height="14">
		<path d="M8 13.5V3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
		<path
			d="M3.5 7.5 8 3l4.5 4.5"
			stroke="currentColor"
			stroke-width="1.6"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
	</svg>
	<span>Back to top</span>
</button>
