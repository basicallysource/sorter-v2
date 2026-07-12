<script lang="ts">
	import { api, type Analytics } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import SeriesChart, { type SeriesPoint } from './SeriesChart.svelte';
	import DonutChart, { type DonutSegment } from './DonutChart.svelte';
	import BarList, { type BarItem } from './BarList.svelte';
	import ChartCard from './ChartCard.svelte';

	let {
		machineId,
		ownerId,
		scope,
		showTotals = true
	}: {
		machineId?: string;
		ownerId?: string;
		scope?: 'mine' | 'all';
		showTotals?: boolean;
	} = $props();

	let data = $state<Analytics | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		// Re-fetch whenever the selected machine set changes.
		const params = { machineId, ownerId, scope };
		void params.machineId;
		void params.ownerId;
		void params.scope;
		loading = true;
		error = null;
		api
			.getAnalytics(params)
			.then((d) => {
				data = d;
			})
			.catch((e: unknown) => {
				error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to load analytics';
			})
			.finally(() => {
				loading = false;
			});
	});

	const isMulti = $derived((data?.scope.machine_count ?? 0) > 1);

	// Time-series projections.
	const piecesPerDay = $derived<SeriesPoint[]>((data?.timeseries ?? []).map((p) => ({ date: p.day, value: p.pieces_seen })));
	const cumulativePieces = $derived<SeriesPoint[]>((data?.timeseries ?? []).map((p) => ({ date: p.day, value: p.cumulative_pieces })));
	const avgPpm = $derived<SeriesPoint[]>((data?.timeseries ?? []).map((p) => ({ date: p.day, value: p.avg_ppm })));
	const capacity = $derived<SeriesPoint[]>((data?.timeseries ?? []).map((p) => ({ date: p.day, value: p.capacity_per_day })));
	const machinesOverTime = $derived<SeriesPoint[]>((data?.timeseries ?? []).map((p) => ({ date: p.day, value: p.cumulative_machines })));

	const PALETTE = [
		'var(--color-primary)',
		'var(--color-info)',
		'var(--color-success)',
		'var(--color-warning-strong)',
		'var(--color-danger)',
		'color-mix(in srgb, var(--color-primary) 55%, var(--color-bg))',
		'color-mix(in srgb, var(--color-info) 55%, var(--color-bg))',
		'color-mix(in srgb, var(--color-success) 55%, var(--color-bg))'
	];

	function statusColor(label: string): string {
		switch (label) {
			case 'classified':
				return 'var(--color-success)';
			case 'failed':
			case 'multi_drop_fail':
				return 'var(--color-danger)';
			case 'not_found':
				return 'var(--color-primary)';
			case 'unknown':
				return 'var(--color-warning-strong)';
			case 'pending':
			case 'classifying':
				return 'var(--color-info)';
			default:
				return 'var(--color-text-muted)';
		}
	}

	const statusSegments = $derived<DonutSegment[]>(
		(data?.distributions.by_status ?? []).map((s) => ({ label: s.label, value: s.value, color: statusColor(s.label) }))
	);
	const machineSegments = $derived<DonutSegment[]>(
		(data?.distributions.by_machine ?? []).map((m, i) => ({ label: m.label, value: m.value, color: PALETTE[i % PALETTE.length] }))
	);
	const topParts = $derived<BarItem[]>(
		(data?.distributions.top_parts ?? []).map((p) => ({ label: p.part_name || p.part_id || '—', sublabel: p.part_id, value: p.value }))
	);
	const topColors = $derived<BarItem[]>(
		(data?.distributions.top_colors ?? []).map((c) => ({ label: c.color_name || c.color_id || '—', value: c.value }))
	);

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString() : '—';
	}
	function ppm(n: number | null | undefined): string {
		return n && n > 0 ? n.toFixed(1) : '—';
	}
	function duration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '—';
		const h = seconds / 3600;
		return h >= 1 ? `${h.toFixed(1)}h` : `${Math.round(seconds / 60)}m`;
	}

	const totalsCards = $derived(
		data
			? [
					{ label: 'Pieces counted', value: num(data.totals.pieces_seen) },
					{ label: 'Distributed', value: num(data.totals.distributed) },
					{ label: 'Overall PPM', value: ppm(data.totals.overall_ppm) },
					{ label: 'Capacity / day', value: num(data.totals.capacity_recent) },
					{ label: 'Unique parts', value: num(data.totals.unique_parts) },
					{ label: 'Unique colors', value: num(data.totals.unique_colors) },
					{ label: 'Active time', value: duration(data.totals.active_seconds) },
					{ label: isMulti ? 'Machines' : 'Classified', value: isMulti ? num(data.totals.machines) : num(data.totals.classified) }
				]
			: []
	);
</script>

{#if loading}
	<div class="flex justify-center py-10"><Spinner /></div>
{:else if error}
	<div class="bg-primary/8 p-3 text-sm text-primary">{error}</div>
{:else if data}
	{#if showTotals}
		<div class="grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-4">
			{#each totalsCards as cell (cell.label)}
				<div class="flex flex-col items-center bg-surface py-4">
					<span class="text-xl font-bold text-text tabular-nums">{cell.value}</span>
					<span class="mt-0.5 text-center text-[10px] uppercase tracking-wider text-text-muted">{cell.label}</span>
				</div>
			{/each}
		</div>
	{/if}

	{#if data.timeseries.length === 0}
		<div class="mt-4 border border-border bg-surface p-8 text-center text-sm text-text-muted">
			No sorting activity recorded yet — charts appear once pieces are synced.
		</div>
	{:else}
		<!-- Time-series -->
		<div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
			<ChartCard title="Pieces per day" subtitle="Pieces seen each day">
				<SeriesChart points={piecesPerDay} kind="bar" />
			</ChartCard>
			<ChartCard title="Total pieces" subtitle="Cumulative pieces seen">
				<SeriesChart points={cumulativePieces} color="var(--color-info)" />
			</ChartCard>
			<ChartCard title="Average PPM" subtitle="Mean per-machine pieces/min per day">
				<SeriesChart points={avgPpm} color="var(--color-success)" formatValue={(v) => v.toFixed(1)} />
			</ChartCard>
			<ChartCard title="Sorting capacity" subtitle="Theoretical pieces/day at that day’s PPM (24h)">
				<SeriesChart points={capacity} color="var(--color-warning-strong)" />
			</ChartCard>
			{#if isMulti}
				<ChartCard title="Machines over time" subtitle="Cumulative machines seen">
					<SeriesChart points={machinesOverTime} color="var(--color-primary)" />
				</ChartCard>
			{/if}
		</div>

		<!-- Distributions -->
		<div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
			<div class="border border-border bg-surface">
				<div class="border-b border-border bg-bg px-4 py-2">
					<h3 class="text-sm font-semibold text-text">Classification outcomes</h3>
				</div>
				<div class="p-4"><DonutChart segments={statusSegments} centerLabel="pieces" /></div>
			</div>

			{#if isMulti && machineSegments.length > 0}
				<div class="border border-border bg-surface">
					<div class="border-b border-border bg-bg px-4 py-2">
						<h3 class="text-sm font-semibold text-text">Pieces by machine</h3>
					</div>
					<div class="p-4"><DonutChart segments={machineSegments} centerLabel="pieces" /></div>
				</div>
			{/if}

			<div class="border border-border bg-surface">
				<div class="border-b border-border bg-bg px-4 py-2">
					<h3 class="text-sm font-semibold text-text">Top parts</h3>
				</div>
				<div class="p-4"><BarList items={topParts} /></div>
			</div>

			<div class="border border-border bg-surface">
				<div class="border-b border-border bg-bg px-4 py-2">
					<h3 class="text-sm font-semibold text-text">Top colors</h3>
				</div>
				<div class="p-4"><BarList items={topColors} color="color-mix(in srgb, var(--color-info) 70%, transparent)" /></div>
			</div>
		</div>
	{/if}
{/if}
