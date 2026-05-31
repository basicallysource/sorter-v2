<script lang="ts">
	// Inline editable number: shows the value as plain text, but on hover/focus it
	// reveals a bordered field you can click into and type directly — so the slider
	// value isn't drag-only. Binds the same value as its companion slider.
	let {
		value = $bindable(),
		min,
		max
	}: {
		value: number;
		min?: number;
		max?: number;
	} = $props();
</script>

<input
	type="number"
	bind:value
	{min}
	{max}
	class="w-14 border border-transparent bg-transparent px-1 text-text tabular-nums transition-colors hover:border-border hover:bg-bg focus:border-primary focus:bg-bg focus:outline-none"
/>
