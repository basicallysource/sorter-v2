<script lang="ts">
	import { api, type Analytics } from '$lib/api';
	import ChartLine from '@lucide/svelte/icons/chart-line';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import { sentence } from '$lib/text';
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

	// One slice a machine: the primary and the neutrals, steps apart. The status colors keep
	// their meaning, so no machine is drawn in green or red.
	const PALETTE = [
		'var(--primary)',
		'var(--ink)',
		'var(--ink-muted)',
		'color-mix(in srgb, var(--primary) 55%, var(--surface))',
		'color-mix(in srgb, var(--ink) 55%, var(--surface))',
		'var(--ink-faint)',
		'color-mix(in srgb, var(--primary) 30%, var(--surface))',
		'var(--line-strong)'
	];

	function statusColor(label: string): string {
		switch (label) {
			case 'classified':
				return 'var(--success)';
			case 'failed':
			case 'multi_drop_fail':
				return 'var(--danger)';
			case 'not_found':
				return 'var(--primary)';
			case 'unknown':
				return 'var(--warning-ink)';
			case 'pending':
			case 'classifying':
				return 'var(--info)';
			default:
				return 'var(--ink-muted)';
		}
	}

	const statusSegments = $derived<DonutSegment[]>(
		(data?.distributions.by_status ?? []).map((s) => ({
			key: s.label,
			label: sentence(s.label),
			value: s.value,
			color: statusColor(s.label)
		}))
	);
	const machineSegments = $derived.by<DonutSegment[]>(() => {
		const rows = data?.distributions.by_machine ?? [];
		// Machine names aren't unique across the fleet — tag the collisions so the
		// legend doesn't show three identical rows.
		const dupes = new Set(rows.map((m) => m.label).filter((l, i, all) => all.indexOf(l) !== i));
		return rows.map((m, i) => ({
			key: m.machine_id,
			label: dupes.has(m.label) ? `${m.label}, ${m.machine_id.slice(0, 6)}` : m.label,
			value: m.value,
			color: PALETTE[i % PALETTE.length]
		}));
	});
	const topParts = $derived<BarItem[]>(
		(data?.distributions.top_parts ?? []).map((p, i) => ({
			key: p.part_id ?? `part-${i}`,
			label: p.part_name || p.part_id || '-',
			sublabel: p.part_id,
			value: p.value
		}))
	);
	const topColors = $derived<BarItem[]>(
		(data?.distributions.top_colors ?? []).map((c, i) => ({
			key: c.color_id ?? `color-${i}`,
			label: c.color_name || c.color_id || '-',
			value: c.value
		}))
	);

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString() : '-';
	}
	function ppm(n: number | null | undefined): string {
		return n && n > 0 ? n.toFixed(1) : '-';
	}
	function duration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '-';
		const h = seconds / 3600;
		return h >= 1 ? `${h.toFixed(1)}h` : `${Math.round(seconds / 60)}m`;
	}

	const totalsCards = $derived(
		data
			? [
					{ label: 'Pieces counted', value: num(data.totals.pieces_seen) },
					{ label: 'Distributed', value: num(data.totals.distributed) },
					{ label: 'Pieces a minute', value: ppm(data.totals.overall_ppm) },
					{ label: 'Capacity a day', value: num(data.totals.capacity_recent) },
					{ label: 'Unique parts', value: num(data.totals.unique_parts) },
					{ label: 'Unique colors', value: num(data.totals.unique_colors) },
					{ label: 'Active time', value: duration(data.totals.active_seconds) },
					{ label: isMulti ? 'Machines' : 'Classified', value: isMulti ? num(data.totals.machines) : num(data.totals.classified) }
				]
			: []
	);
</script>

{#if loading}
	<div class="flex justify-center py-10"><Spinner size={32} /></div>
{:else if error}
	<Alert tone="danger">{error}</Alert>
{:else if data}
	<div class="flex flex-col gap-(--gap-panels)">
		{#if showTotals}
			<div class="overflow-hidden rounded-panel bg-surface">
				<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
					{#each totalsCards as cell (cell.label)}
						<div class="border-t border-l border-line"><Stat label={cell.label} value={cell.value} /></div>
					{/each}
				</div>
			</div>
		{/if}

		{#if data.timeseries.length === 0}
			<Panel>
				<EmptyState icon={ChartLine} title="No sorting activity yet">
					The charts appear once a machine has synced its pieces.
				</EmptyState>
			</Panel>
		{:else}
			<div class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-2">
				<ChartCard title="Pieces per day" subtitle="Pieces seen each day.">
					<SeriesChart points={piecesPerDay} kind="bar" />
				</ChartCard>
				<ChartCard title="Total pieces" subtitle="Pieces seen, added up.">
					<SeriesChart points={cumulativePieces} />
				</ChartCard>
				<ChartCard title="Average pieces a minute" subtitle="Each day's mean across machines.">
					<SeriesChart points={avgPpm} formatValue={(v) => v.toFixed(1)} />
				</ChartCard>
				<ChartCard title="Sorting capacity" subtitle="Pieces a day at that day's rate, sorting all day.">
					<SeriesChart points={capacity} />
				</ChartCard>
				{#if isMulti}
					<ChartCard title="Machines over time" subtitle="Machines seen, added up.">
						<SeriesChart points={machinesOverTime} />
					</ChartCard>
				{/if}
			</div>

			<div class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-2">
				<ChartCard title="Classification outcomes">
					<DonutChart segments={statusSegments} centerLabel="pieces" />
				</ChartCard>
				{#if isMulti && machineSegments.length > 0}
					<ChartCard title="Pieces by machine">
						<DonutChart segments={machineSegments} centerLabel="pieces" />
					</ChartCard>
				{/if}
				<ChartCard title="Top parts">
					<BarList items={topParts} />
				</ChartCard>
				<ChartCard title="Top colors">
					<BarList items={topColors} />
				</ChartCard>
			</div>
		{/if}
	</div>
{/if}
