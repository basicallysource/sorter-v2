<script lang="ts">
	export type Overview = {
		total_runs: number;
		total_pieces: number;
		classified_pieces: number;
		distributed_pieces: number;
		unique_parts: number;
		unique_colors: number;
		first_seen: number | null;
		last_seen: number | null;
	};

	export type LifetimeDay = {
		day: string;
		seconds_powered: number;
		seconds_sorted: number;
		pieces_seen: number;
		pieces_classified: number;
		pieces_distributed: number;
	};

	export type Lifetime = {
		seconds_sorted: number;
		seconds_powered: number;
		pieces_seen: number;
		pieces_classified: number;
		pieces_distributed: number;
		overall_ppm: number;
		best_hour_ppm: number;
		active_days: number;
		first_hour: number | null;
		last_hour: number | null;
		daily: LifetimeDay[];
	};

	export type ValueBucket = { pieces: number; priced_pieces: number; value_usd: number };
	export type ValueStats = { currency: string; all_time: ValueBucket; last_24h: ValueBucket };

	import Panel from '$lib/components/ui/Panel.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';

	let {
		overview,
		lifetime,
		value
	}: {
		overview: Overview | null;
		lifetime: Lifetime | null;
		value: ValueStats | null;
	} = $props();

	function formatDuration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0h 0m';
		const total_min = Math.floor(seconds / 60);
		const days = Math.floor(total_min / 1440);
		const hours = Math.floor((total_min % 1440) / 60);
		const mins = total_min % 60;
		if (days > 0) return `${days}d ${hours}h`;
		return `${hours}h ${mins}m`;
	}

	function formatHours(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0';
		return (seconds / 3600).toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	function formatPpm(ppm: number | null | undefined): string {
		if (!ppm || ppm <= 0) return '—';
		return ppm.toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	function formatUsd(amount: number | null | undefined): string {
		if (typeof amount !== 'number') return '—';
		return amount.toLocaleString(undefined, {
			style: 'currency',
			currency: 'USD',
			maximumFractionDigits: 2
		});
	}

	function formatDate(ts: number | null): string {
		if (ts == null) return '—';
		return new Date(ts * 1000).toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	}

	let utilizationPct = $derived(
		lifetime && lifetime.seconds_powered > 0
			? (lifetime.seconds_sorted / lifetime.seconds_powered) * 100
			: 0
	);

	const dash = '—';
	const count = (n: number | undefined) => (n === undefined ? dash : n.toLocaleString());

	const cells = $derived<{ label: string; value: string; hint?: string }[]>([
		{ label: 'Pieces seen', value: count(overview?.total_pieces) },
		{ label: 'Distributed', value: count(overview?.distributed_pieces) },
		{ label: 'Classified', value: count(overview?.classified_pieces) },
		{ label: 'Runs', value: count(overview?.total_runs) },
		{
			label: 'Hours sorted',
			value: lifetime ? formatHours(lifetime.seconds_sorted) : dash,
			hint: lifetime ? `${formatDuration(lifetime.seconds_sorted)} active` : undefined
		},
		{
			label: 'Hours powered',
			value: lifetime ? formatHours(lifetime.seconds_powered) : dash,
			hint: lifetime ? `${formatDuration(lifetime.seconds_powered)} on` : undefined
		},
		{ label: 'Utilization', value: lifetime ? `${utilizationPct.toFixed(0)}%` : dash },
		{ label: 'Active days', value: count(lifetime?.active_days) },
		{
			label: 'Throughput',
			value: lifetime ? formatPpm(lifetime.overall_ppm) : dash,
			hint: 'avg pieces/min'
		},
		{
			label: 'Best hour',
			value: lifetime ? formatPpm(lifetime.best_hour_ppm) : dash,
			hint: 'peak pieces/min'
		},
		{ label: 'Unique parts', value: count(overview?.unique_parts) },
		{ label: 'Unique colors', value: count(overview?.unique_colors) },
		{
			label: 'Total value',
			value: value ? formatUsd(value.all_time.value_usd) : dash,
			hint: value
				? `${value.all_time.priced_pieces.toLocaleString()} of ${value.all_time.pieces.toLocaleString()} priced`
				: undefined
		},
		{
			label: 'Value, last 24 hours',
			value: value ? formatUsd(value.last_24h.value_usd) : dash,
			hint: value
				? `${value.last_24h.priced_pieces.toLocaleString()} of ${value.last_24h.pieces.toLocaleString()} priced`
				: undefined
		},
		{ label: 'First seen', value: overview ? formatDate(overview.first_seen) : dash },
		{ label: 'Last seen', value: overview ? formatDate(overview.last_seen) : dash }
	]);
</script>

<Panel
	title="Lifetime"
	description="Every piece seen across all saved runs; value from the BrickLink moving average."
	flush
>
	<div class="grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
		{#each cells as cell (cell.label)}
			<div class="bg-surface">
				<Stat label={cell.label} value={cell.value} hint={cell.hint} />
			</div>
		{/each}
	</div>
</Panel>
