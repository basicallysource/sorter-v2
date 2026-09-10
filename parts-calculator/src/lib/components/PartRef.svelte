<script lang="ts">
	// A printed part named in the middle of a sentence, as a link to its page.
	// The counterpart of HardwareRef, and deliberately plainer: a part has no
	// head silhouette or thread colour to carry, so the name and the underline
	// on hover are the whole affordance.
	import type { Part } from '$lib/filament';

	let { part }: { part: Part } = $props();
</script>

<a class="part-ref" href="/part/{part.id}" title="View {part.name} details">{part.name}</a>

<style>
	.part-ref {
		color: inherit;
		text-decoration: none;
	}
	.part-ref:hover,
	.part-ref:focus-visible {
		text-decoration: underline;
	}
</style>
