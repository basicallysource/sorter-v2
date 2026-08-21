<script lang="ts">
	// An assembly's description or joining note, with every `[[hw:<id>]]`
	// reference in it rendered as the real hardware item rather than left as a
	// token. `as` picks the wrapper: a block `p` for a description, an inline
	// `span` for a note that sits in a flex row next to its badge.
	import HardwareRef from './HardwareRef.svelte';
	import { descriptionSegments } from '$lib/filament';

	let {
		text,
		as = 'p',
		class: className = ''
	}: { text: string; as?: 'p' | 'span'; class?: string } = $props();
	const segments = $derived(descriptionSegments(text));
</script>

<svelte:element this={as} class={className}>{#each segments as seg, i (i)}{#if seg.kind === 'text'}{seg.text}{:else}<HardwareRef
			hw={seg.hw}
		/>{/if}{/each}</svelte:element>
