<script lang="ts">
	// A fastener named in the middle of a sentence: the same head silhouette and
	// thread-size colour the hardware list uses, in front of the same parts-list
	// name. So "M5 × 16 mm socket/button head" in a description and the row you
	// buy it from are visibly one item, instead of a bare "M5×16" that matches
	// nothing in the list.
	//
	// Deliberately not bold and deliberately no "A" tag: this is running prose,
	// and a sentence with three fasteners in it turns into a row of badges
	// otherwise. The tag belongs on the hardware rows, where you are shopping.
	import HardwareIcon from './HardwareIcon.svelte';
	import type { Hardware } from '$lib/filament';

	let { hw }: { hw: Hardware } = $props();
</script>

<a class="hw-ref" href="/part/{hw.id}" title="View {hw.name} details"><HardwareIcon
		{hw}
		size={13}
	/><span class="hw-ref-name">{hw.name}</span></a>

<style>
	/* Kept on one line so a fastener never breaks across two: the symbol is only
	   readable next to the name it belongs to. */
	.hw-ref {
		white-space: nowrap;
		color: inherit;
		text-decoration: none;
	}
	.hw-ref:hover .hw-ref-name,
	.hw-ref:focus-visible .hw-ref-name {
		text-decoration: underline;
	}
	/* The icon is a box on a text baseline; nudge it down so it sits on the line
	   rather than riding above it. */
	.hw-ref :global(svg) {
		display: inline-block;
		vertical-align: -0.2em;
		margin-right: 0.2em;
	}
</style>
