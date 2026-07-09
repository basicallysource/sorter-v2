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
</script>

{#snippet statCard(label: string, value_text: string, sub: string | null = null)}
	<div class="border border-border bg-surface px-4 py-3">
		<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">{label}</div>
		<div class="mt-1 text-2xl font-bold text-text">{value_text}</div>
		{#if sub}
			<div class="mt-0.5 text-sm text-text-muted">{sub}</div>
		{/if}
	</div>
{/snippet}

<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">
	Lifetime
	<span class="ml-1 font-normal normal-case text-text-muted"
		>— every piece seen across all saved runs; value from BrickLink moving avg</span
	>
</h3>
<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
	{@render statCard('Pieces seen', overview ? overview.total_pieces.toLocaleString() : '—')}
	{@render statCard('Distributed', overview ? overview.distributed_pieces.toLocaleString() : '—')}
	{@render statCard('Classified', overview ? overview.classified_pieces.toLocaleString() : '—')}
	{@render statCard('Runs', overview ? overview.total_runs.toLocaleString() : '—')}
	{@render statCard(
		'Hours sorted',
		lifetime ? formatHours(lifetime.seconds_sorted) : '—',
		lifetime ? formatDuration(lifetime.seconds_sorted) + ' active' : null
	)}
	{@render statCard(
		'Hours powered',
		lifetime ? formatHours(lifetime.seconds_powered) : '—',
		lifetime ? formatDuration(lifetime.seconds_powered) + ' on' : null
	)}
	{@render statCard('Utilization', lifetime ? `${utilizationPct.toFixed(0)}%` : '—')}
	{@render statCard('Active days', lifetime ? lifetime.active_days.toLocaleString() : '—')}
	{@render statCard(
		'Throughput',
		lifetime ? formatPpm(lifetime.overall_ppm) : '—',
		'avg pieces/min'
	)}
	{@render statCard(
		'Best hour',
		lifetime ? formatPpm(lifetime.best_hour_ppm) : '—',
		'peak pieces/min'
	)}
	{@render statCard('Unique parts', overview ? overview.unique_parts.toLocaleString() : '—')}
	{@render statCard('Unique colors', overview ? overview.unique_colors.toLocaleString() : '—')}
	{@render statCard(
		'Total value',
		value ? formatUsd(value.all_time.value_usd) : '—',
		value
			? `${value.all_time.priced_pieces.toLocaleString()} of ${value.all_time.pieces.toLocaleString()} pieces priced`
			: null
	)}
	{@render statCard(
		'Value · last 24h',
		value ? formatUsd(value.last_24h.value_usd) : '—',
		value
			? `${value.last_24h.priced_pieces.toLocaleString()} of ${value.last_24h.pieces.toLocaleString()} pieces priced`
			: null
	)}
	{@render statCard('First seen', overview ? formatDate(overview.first_seen) : '—')}
	{@render statCard('Last seen', overview ? formatDate(overview.last_seen) : '—')}
</div>
