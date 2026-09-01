<script lang="ts">
	import { Skeleton } from '$lib/components/primitives';
	import { LEGO_COLORS } from '$lib/lego-colors';
	import SeriesChart from './SeriesChart.svelte';
	import DonutChart, { type DonutSegment } from './DonutChart.svelte';

	type Aggregates = {
		per_day: { date: string; count: number }[];
		status_breakdown: { status: string; count: number }[];
		unique_parts_cumulative: { date: string; count: number }[];
		ppm_per_day: { date: string; ppm: number }[];
		per_color: { color_id: string | null; color_name: string | null; count: number }[];
		top_parts: { part_id: string | null; part_name: string | null; count: number }[];
		value_per_day: { date: string; value: number }[];
	};

	let { endpointBase }: { endpointBase: string } = $props();

	let aggregates = $state<Aggregates | null>(null);
	let error = $state(false);

	async function load(base: string): Promise<void> {
		try {
			const res = await fetch(`${base}/api/pieces/aggregates?days=365`);
			if (!res.ok) {
				error = true;
				return;
			}
			aggregates = (await res.json()) as Aggregates;
			error = false;
		} catch {
			error = true;
		}
	}

	// Lazy: the charts live below the fold — let the stat cards and the pieces
	// list land first, then pull the (backend-cached) aggregate payload.
	let loaded_base: string | null = null;
	$effect(() => {
		const base = endpointBase;
		if (base === loaded_base) return;
		const id = setTimeout(() => {
			loaded_base = base;
			void load(base);
		}, 200);
		return () => clearTimeout(id);
	});

	const STATUS_LABELS: Record<string, string> = {
		classified: 'Classified',
		failed: 'ID failed',
		unknown: 'Unknown',
		not_found: 'Not found',
		multi_drop_fail: 'Multi drop',
		dead: 'Timed out',
		pending: 'Pending',
		classifying: 'Classifying'
	};

	const STATUS_COLORS: Record<string, string> = {
		classified: 'var(--color-success)',
		failed: 'var(--color-danger)',
		unknown: 'var(--color-warning)',
		not_found: 'var(--color-warning-dark)',
		multi_drop_fail: 'var(--color-danger-dark)',
		dead: 'var(--color-text-muted)',
		pending: 'var(--color-primary)',
		classifying: 'var(--color-primary)'
	};

	const statusSegments = $derived.by<DonutSegment[]>(() => {
		if (!aggregates) return [];
		return aggregates.status_breakdown.map((s) => ({
			label: STATUS_LABELS[s.status] ?? s.status.replace(/_/g, ' '),
			value: s.count,
			color: STATUS_COLORS[s.status] ?? 'var(--color-border)'
		}));
	});

	function legoHex(color_id: string | null, color_name: string | null): string {
		if (color_id) {
			const by_id = LEGO_COLORS.find((c) => c.id === color_id);
			if (by_id) return by_id.hex;
		}
		if (color_name) {
			const lower = color_name.toLowerCase();
			const by_name = LEGO_COLORS.find((c) => c.name.toLowerCase() === lower);
			if (by_name) return by_name.hex;
		}
		return 'var(--color-text-muted)';
	}

	const maxColorCount = $derived(
		aggregates ? Math.max(1, ...aggregates.per_color.map((c) => c.count)) : 1
	);
	const maxPartCount = $derived(
		aggregates ? Math.max(1, ...aggregates.top_parts.map((p) => p.count)) : 1
	);
</script>

{#snippet chartCard(title: string, sub: string | null, body: import('svelte').Snippet)}
	<div class="flex flex-col border border-border bg-surface">
		<div class="border-b border-border bg-bg px-3 py-2">
			<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">{title}</span>
			{#if sub}
				<span class="ml-2 text-xs text-text-muted">{sub}</span>
			{/if}
		</div>
		<div class="flex-1 p-3">
			{@render body()}
		</div>
	</div>
{/snippet}

<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">Trends</h3>
{#if aggregates === null}
	{#if error}
		<div class="border border-border bg-surface p-4 text-sm text-text-muted">
			Could not load chart data.
		</div>
	{:else}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
			{#each Array(6) as _, i (i)}
				<Skeleton class="h-48 w-full" />
			{/each}
		</div>
	{/if}
{:else}
	<div class="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
		{#snippet piecesPerDay()}
			<SeriesChart
				points={(aggregates?.per_day ?? []).map((p) => ({ date: p.date, value: p.count }))}
				kind="bar"
			/>
		{/snippet}
		{@render chartCard('Pieces per day', 'last year, dead excluded', piecesPerDay)}

		{#snippet ppmSeries()}
			<SeriesChart
				points={(aggregates?.ppm_per_day ?? []).map((p) => ({ date: p.date, value: p.ppm }))}
				kind="line"
				color="var(--color-success)"
			/>
		{/snippet}
		{@render chartCard('Throughput per day', 'pieces/min while sorting', ppmSeries)}

		{#snippet uniqueParts()}
			<SeriesChart
				points={(aggregates?.unique_parts_cumulative ?? []).map((p) => ({
					date: p.date,
					value: p.count
				}))}
				kind="line"
				color="var(--color-info)"
			/>
		{/snippet}
		{@render chartCard('Unique parts seen', 'cumulative, all time', uniqueParts)}

		{#snippet statusDonut()}
			<DonutChart segments={statusSegments} centerLabel="pieces" />
		{/snippet}
		{@render chartCard('Classification outcomes', 'all time', statusDonut)}

		{#snippet colorBars()}
			{@const colors = aggregates?.per_color ?? []}
			{#if colors.length === 0}
				<div class="flex h-32 items-center justify-center text-sm text-text-muted">
					No data yet.
				</div>
			{:else}
				<div class="flex flex-col gap-1.5">
					{#each colors as c (c.color_id ?? c.color_name ?? '?')}
						<div class="flex items-center gap-2 text-sm">
							<span class="w-36 truncate text-text" title={c.color_name ?? c.color_id ?? ''}>
								{c.color_name ?? c.color_id ?? '—'}
							</span>
							<div class="h-3.5 flex-1 bg-bg">
								<div
									class="h-full border border-border"
									style:width={`${Math.max(1, (c.count / maxColorCount) * 100)}%`}
									style:background-color={legoHex(c.color_id, c.color_name)}
								></div>
							</div>
							<span class="w-14 text-right tabular-nums text-text-muted">
								{c.count.toLocaleString()}
							</span>
						</div>
					{/each}
				</div>
			{/if}
		{/snippet}
		{@render chartCard('Top colors', 'all time, top 20', colorBars)}

		{#snippet partBars()}
			{@const parts = aggregates?.top_parts ?? []}
			{#if parts.length === 0}
				<div class="flex h-32 items-center justify-center text-sm text-text-muted">
					No data yet.
				</div>
			{:else}
				<div class="flex flex-col gap-1.5">
					{#each parts as p (p.part_id ?? p.part_name ?? '?')}
						<div class="flex items-center gap-2 text-sm">
							<span class="w-16 flex-shrink-0 truncate font-mono text-xs text-text-muted">
								{p.part_id ?? '—'}
							</span>
							<span class="w-36 truncate text-text" title={p.part_name ?? ''}>
								{p.part_name ?? '—'}
							</span>
							<div class="h-3.5 flex-1 bg-bg">
								<div
									class="h-full bg-primary/70"
									style:width={`${Math.max(1, (p.count / maxPartCount) * 100)}%`}
								></div>
							</div>
							<span class="w-14 text-right tabular-nums text-text-muted">
								{p.count.toLocaleString()}
							</span>
						</div>
					{/each}
				</div>
			{/if}
		{/snippet}
		{@render chartCard('Top parts', 'all time, top 20', partBars)}
	</div>
{/if}
