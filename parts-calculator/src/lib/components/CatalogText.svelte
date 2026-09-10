<script lang="ts">
	// Any prose out of the catalog — a description, a joining note, a version
	// message — with every `[[hw:<id>]]` and `[[part:<id>]]` reference in it
	// rendered as the real hardware item or part rather than left as a token.
	// `as` picks the wrapper: a block `p` for a description, an inline `span`
	// for a note that sits in a flex row next to its badge.
	import HardwareRef from './HardwareRef.svelte';
	import PartRef from './PartRef.svelte';
	import { descriptionSegments } from '$lib/filament';

	let {
		text,
		as = 'p',
		class: className = ''
	}: { text: string; as?: 'p' | 'span'; class?: string } = $props();
	const segments = $derived(descriptionSegments(text));
</script>

<svelte:element this={as} class={className}>{#each segments as seg, i (i)}{#if seg.kind === 'text'}{seg.text}{:else if seg.kind === 'hw'}<HardwareRef
			hw={seg.hw}
		/>{:else}<PartRef part={seg.part} />{/if}{/each}</svelte:element>
