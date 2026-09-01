<script lang="ts">
	// A small green "A" tag marking a part that has an interchangeable alternative
	// (e.g. socket vs button head — either works). Green + "A" rather than a blue
	// "i" so it doesn't read as a generic "more info" icon. Hover (or tap) pops
	// the explanation instantly; a string value names the specific alternative.
	// `size` shrinks it for inline use inside a sentence, where the list's 18px
	// would set the line height on its own.
	import Popover from '$lib/components/Popover.svelte';
	let { value, size = 18 }: { value?: string | boolean | null; size?: number } = $props();
	const detail = $derived(typeof value === 'string' && value.trim() ? value : null);
</script>

{#if value}
	<Popover label="Interchangeable alternative" width="w-64">
		{#snippet trigger({ toggle })}
			<button
				type="button"
				class="inline-flex shrink-0 cursor-help items-center justify-center px-1 font-bold leading-none text-white"
				style="background: var(--color-success); height: {size}px; min-width: {size}px; font-size: {(
					size * 0.04
				).toFixed(3)}rem"
				aria-label="Interchangeable alternative"
				onclick={(e) => {
					e.preventDefault();
					e.stopPropagation();
					toggle();
				}}
			>A</button>
		{/snippet}
		<p class="font-semibold text-text">Interchangeable alternative</p>
		<p class="mt-1">{detail ?? 'Either variant works here (e.g. socket vs button head).'}</p>
	</Popover>
{/if}
