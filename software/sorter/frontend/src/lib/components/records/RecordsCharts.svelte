<script lang="ts">
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import { findLegoColor } from '$lib/pieces/colors';
	import BarList from './BarList.svelte';
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
		classified: 'var(--success)',
		failed: 'var(--danger)',
		unknown: 'var(--warning)',
		not_found: 'var(--warning-ink)',
		multi_drop_fail: 'var(--danger-ink)',
		dead: 'var(--ink-muted)',
		pending: 'var(--primary)',
		classifying: 'var(--primary)'
	};

	const statusSegments = $derived.by<DonutSegment[]>(() => {
		if (!aggregates) return [];
		return aggregates.status_breakdown.map((s) => ({
			label: STATUS_LABELS[s.status] ?? s.status.replace(/_/g, ' '),
			value: s.count,
			color: STATUS_COLORS[s.status] ?? 'var(--line)'
		}));
	});

	function legoHex(color_id: string | null, color_name: string | null): string {
		return findLegoColor(color_id, color_name)?.hex ?? 'var(--ink-muted)';
	}</script>

<section class="flex flex-col gap-3">
	<h2 class="text-base font-semibold text-ink">Trends</h2>
	{#if aggregates === null}
		{#if error}
			<Alert tone="warning">Could not load the chart data.</Alert>
		{:else}
			<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 2xl:grid-cols-3" aria-busy="true">
				{#each Array(6) as _, i (i)}
					<Skeleton class="h-64 w-full" />
				{/each}
			</div>
		{/if}
	{:else}
		<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 2xl:grid-cols-3">
			<Panel title="Pieces per day" description="Last year, dead pieces excluded.">
				<SeriesChart
					points={(aggregates.per_day ?? []).map((p) => ({ date: p.date, value: p.count }))}
					kind="bar"
				/>
			</Panel>
			<Panel title="Throughput per day" description="Pieces a minute while sorting.">
				<SeriesChart
					points={(aggregates.ppm_per_day ?? []).map((p) => ({ date: p.date, value: p.ppm }))}
				/>
			</Panel>
			<Panel title="Unique parts seen" description="Cumulative, all time.">
				<SeriesChart
					points={(aggregates.unique_parts_cumulative ?? []).map((p) => ({
						date: p.date,
						value: p.count
					}))}
				/>
			</Panel>
			<Panel title="Classification outcomes" description="All time.">
				<DonutChart segments={statusSegments} centerLabel="pieces" />
			</Panel>
			<Panel title="Top colors" description="All time, top 20.">
				<BarList
					rows={(aggregates.per_color ?? []).map((c) => ({
						key: c.color_id ?? c.color_name ?? '?',
						label: c.color_name ?? c.color_id ?? '—',
						count: c.count,
						fill: legoHex(c.color_id, c.color_name)
					}))}
				/>
			</Panel>
			<Panel title="Top parts" description="All time, top 20.">
				<BarList
					rows={(aggregates.top_parts ?? []).map((p) => ({
						key: p.part_id ?? p.part_name ?? '?',
						code: p.part_id ?? '—',
						label: p.part_name ?? '—',
						count: p.count
					}))}
				/>
			</Panel>
		</div>
	{/if}
</section>
