<script lang="ts">
	// A small green "A" tag marking a part that has an interchangeable alternative
	// (e.g. socket vs button head — either works). Mirrors the docs' red "!"
	// "not in the parts calculator" marker: same 18px footprint, "A" for
	// "alternative" (green) instead of "!" for warning (red). Green + "A" rather
	// than a blue "i" so it doesn't read as a generic "more info" icon. A bare
	// `true` reads "Alternative"; a string says what the alternative is.
	// `size` shrinks it for inline use inside a sentence, where the list's 18px
	// would set the line height on its own.
	let { value, size = 18 }: { value?: string | boolean | null; size?: number } = $props();
	const label = $derived(typeof value === 'string' && value.trim() ? value : 'Alternative');
</script>

{#if value}
	<span
		class="inline-flex shrink-0 cursor-help items-center justify-center px-1 font-bold leading-none text-white"
		style="background: var(--color-success); height: {size}px; min-width: {size}px; font-size: {(
			size * 0.04
		).toFixed(3)}rem"
		title={label}
		aria-label={label}
	>A</span>
{/if}
