<script lang="ts">
	let { signal }: { signal: number } = $props();

	const bars = $derived(
		signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : signal >= 5 ? 1 : 0
	);
</script>

<div class="flex items-end gap-[2px]" aria-label="Signal {signal}%">
	{#each [1, 2, 3, 4] as i (i)}
		<span
			class="w-1 bg-current transition-opacity"
			class:opacity-100={i <= bars}
			class:opacity-20={i > bars}
			style="height: {i * 3 + 2}px"
		></span>
	{/each}
</div>
