<script lang="ts">
	import type { Range } from '$lib/search';

	// Text with the matched characters marked. The matcher hands back a range
	// rather than a substring so the highlight lands on the actual characters
	// that matched, not on every other place the same letters appear.
	//
	// Ranges are computed against the normalised (lowercased, accent-folded)
	// form. For everything the catalog actually contains that is character-for-
	// character the same length as the original, so the indices carry over; the
	// bounds check below is what keeps an exotic decomposition from painting the
	// wrong letters — it drops the highlight rather than misplacing it.
	let { text, range = null }: { text: string; range?: Range | null } = $props();

	const parts = $derived.by(() => {
		if (!range) return null;
		const [a, b] = range;
		if (a < 0 || b > text.length || a >= b) return null;
		return { before: text.slice(0, a), hit: text.slice(a, b), after: text.slice(b) };
	});
</script>

{#if parts}{parts.before}<mark class="bg-primary/[0.14] font-semibold text-text">{parts.hit}</mark
	>{parts.after}{:else}{text}{/if}
