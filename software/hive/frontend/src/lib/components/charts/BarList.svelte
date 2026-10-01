<script lang="ts">
	// Horizontal bar list for ranked categorical data (top parts, top colors).
	// `key` must be unique — labels are not (two colors can share a name).
	export type BarItem = { key: string; label: string; sublabel?: string | null; value: number; swatch?: string | null };

	let {
		items,
		color = 'var(--primary)'
	}: {
		items: BarItem[];
		color?: string;
	} = $props();

	const max = $derived(Math.max(1, ...items.map((i) => i.value)));
</script>

{#if items.length === 0}
	<div class="flex h-24 items-center justify-center text-sm text-ink-muted">No data yet.</div>
{:else}
	<div class="flex flex-col gap-1.5">
		{#each items as item (item.key)}
			<div class="flex items-center gap-2 text-sm">
				{#if item.swatch}
					<span class="size-3 shrink-0 rounded-badge border border-line-strong" style:background-color={item.swatch}></span>
				{/if}
				{#if item.sublabel}
					<span class="w-10 shrink-0 truncate font-mono text-xs text-ink-muted sm:w-14">{item.sublabel}</span>
				{/if}
				<span class="w-20 shrink-0 truncate text-ink sm:w-28" title={item.label}>{item.label}</span>
				<div class="h-3 flex-1 overflow-hidden rounded-badge bg-track">
					<div class="h-full" style="width: {(item.value / max) * 100}%; background: {color}"></div>
				</div>
				<span class="num w-12 shrink-0 text-right text-ink-muted sm:w-16">{item.value.toLocaleString()}</span>
			</div>
		{/each}
	</div>
{/if}
