<script lang="ts">
	let { signal }: { signal: number } = $props();

	const bars = $derived(signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : signal >= 5 ? 1 : 0);
</script>

<span class="flex h-4 items-end gap-[2px]" role="img" aria-label="Signal {signal}%">
	{#each [1, 2, 3, 4] as i (i)}
		<span class="w-[3px] bg-current" class:opacity-20={i > bars} style="height: {i * 3 + 4}px"></span>
	{/each}
</span>
