<script lang="ts">
	// A ranked list of horizontal bars on a well: what a chart of counts by
	// name is. `fill` is a CSS color for data that is a color (a LEGO color);
	// otherwise the bar is the primary, or `tone` when the level means something.
	export type BarRow = {
		key: string;
		label: string;
		count: number;
		// A code shown before the label, in the mono (a part number).
		code?: string;
		// Text after the count (an average duration).
		note?: string;
		fill?: string;
	};

	let {
		rows,
		tone = 'primary',
		labelWidth = 'sm:w-36',
		empty = 'No data yet.'
	}: {
		rows: BarRow[];
		tone?: 'primary' | 'danger';
		// The label's width from sm up (a phone lets it take what is left).
		labelWidth?: string;
		empty?: string;
	} = $props();

	const max = $derived(Math.max(1, ...rows.map((r) => r.count)));
</script>

{#if rows.length === 0}
	<div class="flex h-32 items-center justify-center rounded-control bg-well text-sm text-ink-muted">
		{empty}
	</div>
{:else}
	<ul class="flex flex-col gap-1.5 rounded-control bg-well p-3">
		{#each rows as row (row.key)}
			<li class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm sm:flex-nowrap">
				{#if row.code}
					<span class="w-16 shrink-0 truncate font-mono text-xs text-ink-muted">{row.code}</span>
				{/if}
				<span class="min-w-0 flex-1 truncate text-ink sm:flex-none {labelWidth}" title={row.label}>{row.label}</span>
				<div class="order-last h-3.5 w-full bg-track sm:order-none sm:w-auto sm:flex-1">
					<div
						class="h-full {row.fill ? 'border border-line' : tone === 'danger' ? 'bg-danger' : 'bg-primary'}"
						style:width="{Math.max(1, (row.count / max) * 100)}%"
						style:background-color={row.fill}
					></div>
				</div>
				<span class="num w-14 shrink-0 text-right text-ink-muted">{row.count.toLocaleString()}</span>
				{#if row.note}<span class="w-24 shrink-0 text-right text-xs text-ink-muted">{row.note}</span>{/if}
			</li>
		{/each}
	</ul>
{/if}
