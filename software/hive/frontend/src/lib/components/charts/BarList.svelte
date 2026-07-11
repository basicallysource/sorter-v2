<script lang="ts">
	// Horizontal bar list for ranked categorical data (top parts, top colors).
	export type BarItem = { label: string; sublabel?: string | null; value: number; swatch?: string | null };

	let {
		items,
		color = 'color-mix(in srgb, var(--color-primary) 70%, transparent)'
	}: {
		items: BarItem[];
		color?: string;
	} = $props();

	const max = $derived(Math.max(1, ...items.map((i) => i.value)));
</script>

{#if items.length === 0}
	<div class="flex h-24 items-center justify-center text-sm text-text-muted">No data yet.</div>
{:else}
	<div class="flex flex-col gap-1.5">
		{#each items as item (item.label + (item.sublabel ?? ''))}
			<div class="flex items-center gap-2 text-sm">
				{#if item.swatch}
					<span class="h-3 w-3 flex-shrink-0 border border-border" style:background-color={item.swatch}></span>
				{/if}
				{#if item.sublabel}
					<span class="w-14 flex-shrink-0 truncate font-mono text-xs text-text-muted">{item.sublabel}</span>
				{/if}
				<span class="w-28 flex-shrink-0 truncate text-text" title={item.label}>{item.label}</span>
				<div class="h-4 flex-1 bg-bg">
					<div class="h-full" style="width: {(item.value / max) * 100}%; background: {color}"></div>
				</div>
				<span class="w-16 flex-shrink-0 text-right tabular-nums text-text-muted">{item.value.toLocaleString()}</span>
			</div>
		{/each}
	</div>
{/if}
