<script lang="ts">
	import { onMount } from 'svelte';
	import { Skeleton } from '$lib/components/primitives';
	import SeriesChart from './SeriesChart.svelte';
	import DonutChart, { type DonutSegment } from './DonutChart.svelte';

	type KindSummary = {
		kind: string;
		count: number;
		avg_duration_s: number | null;
		operator_resolved: number;
		auto_resolved: number;
	};

	type Summary = {
		total: number;
		active: number;
		by_kind: KindSummary[];
		by_day: { date: string; count: number }[];
		by_channel: { channel: string; count: number }[];
	};

	type IncidentRow = {
		id: number;
		kind: string;
		channel: string | null;
		channel_label: string | null;
		severity: string | null;
		reason: string | null;
		operator_message: string | null;
		status: string;
		triggered_at: number;
		resolved_at: number | null;
		resolved_by: string | null;
		duration_s: number | null;
	};

	let { endpointBase }: { endpointBase: string } = $props();

	let summary = $state<Summary | null>(null);
	let error = $state(false);
	let rows = $state<IncidentRow[]>([]);
	let rowsLoading = $state(false);

	async function loadSummary(base: string): Promise<void> {
		try {
			const res = await fetch(`${base}/api/incidents/summary`);
			if (!res.ok) {
				error = true;
				return;
			}
			summary = (await res.json()) as Summary;
			error = false;
		} catch {
			error = true;
		}
	}

	async function loadRows(base: string): Promise<void> {
		rowsLoading = true;
		try {
			const res = await fetch(`${base}/api/incidents?limit=25`);
			if (!res.ok) return;
			const json = await res.json();
			rows = Array.isArray(json?.items) ? json.items : [];
		} catch {
			// ignore
		} finally {
			rowsLoading = false;
		}
	}

	onMount(() => {
		void loadSummary(endpointBase);
		void loadRows(endpointBase);
	});

	function formatKind(kind: string): string {
		return kind.replace(/_/g, ' ');
	}

	function formatDuration(seconds: number | null): string {
		if (seconds == null || seconds < 0) return '—';
		if (seconds < 60) return `${Math.round(seconds)}s`;
		const minutes = Math.floor(seconds / 60);
		const secs = Math.round(seconds % 60);
		if (minutes < 60) return `${minutes}m ${secs}s`;
		const hours = Math.floor(minutes / 60);
		return `${hours}h ${minutes % 60}m`;
	}

	function formatTimestamp(ts: number): string {
		return new Date(ts * 1000).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}

	function resolvedByLabel(value: string | null): string {
		if (value === 'operator') return 'Operator';
		if (value === 'superseded') return 'Superseded';
		if (value === 'auto' || value === 'system') return 'Auto';
		return '—';
	}

	const KIND_COLORS = [
		'var(--color-danger)',
		'var(--color-warning)',
		'var(--color-info)',
		'var(--color-primary)',
		'var(--color-success)',
		'var(--color-danger-dark)',
		'var(--color-warning-dark)',
		'var(--color-text-muted)'
	];

	const kindSegments = $derived.by<DonutSegment[]>(() => {
		if (!summary) return [];
		return summary.by_kind.map((k, i) => ({
			label: formatKind(k.kind),
			value: k.count,
			color: KIND_COLORS[i % KIND_COLORS.length]
		}));
	});

	const maxKindCount = $derived(
		summary ? Math.max(1, ...summary.by_kind.map((k) => k.count)) : 1
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

<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">
	Incidents
	<span class="ml-1 font-normal normal-case text-text-muted"
		>— classification-channel clears, chute jams, stepper stalls, and every other
		operator-facing hold this machine has recorded</span
	>
</h3>

{#if summary === null}
	{#if error}
		<div class="border border-border bg-surface p-4 text-sm text-text-muted">
			Could not load incident data.
		</div>
	{:else}
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			{#each Array(4) as _, i (i)}
				<Skeleton class="h-16 w-full" />
			{/each}
		</div>
	{/if}
{:else}
	<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
		{@render statCard('Total incidents', summary.total.toLocaleString())}
		{@render statCard(
			'Currently active',
			summary.active.toLocaleString(),
			summary.active > 0 ? 'awaiting operator or auto-resolve' : null
		)}
		{@render statCard('Distinct kinds', summary.by_kind.length.toLocaleString())}
		{@render statCard(
			'Most frequent',
			summary.by_kind[0] ? formatKind(summary.by_kind[0].kind) : '—',
			summary.by_kind[0] ? `${summary.by_kind[0].count.toLocaleString()} times` : null
		)}
	</div>

	<div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
		{#snippet incidentsPerDay()}
			<SeriesChart
				points={summary?.by_day.map((p) => ({ date: p.date, value: p.count })) ?? []}
				kind="bar"
				color="var(--color-danger)"
			/>
		{/snippet}
		{@render chartCard('Incidents per day', 'last year', incidentsPerDay)}

		{#snippet kindDonut()}
			<DonutChart segments={kindSegments} centerLabel="incidents" />
		{/snippet}
		{@render chartCard('By kind', 'all time', kindDonut)}

		{#snippet kindBars()}
			{#if summary && summary.by_kind.length > 0}
				<div class="flex flex-col gap-1.5">
					{#each summary.by_kind as k (k.kind)}
						<div class="flex items-center gap-2 text-sm">
							<span class="w-40 truncate text-text capitalize" title={formatKind(k.kind)}>
								{formatKind(k.kind)}
							</span>
							<div class="h-3.5 flex-1 bg-bg">
								<div
									class="h-full bg-danger/70"
									style:width={`${Math.max(1, (k.count / maxKindCount) * 100)}%`}
								></div>
							</div>
							<span class="w-12 text-right tabular-nums text-text-muted">
								{k.count.toLocaleString()}
							</span>
							<span class="w-24 text-right text-xs text-text-muted">
								{formatDuration(k.avg_duration_s)} avg
							</span>
						</div>
					{/each}
				</div>
			{:else}
				<div class="flex h-32 items-center justify-center text-sm text-text-muted">
					No incidents recorded.
				</div>
			{/if}
		{/snippet}
		{@render chartCard('Frequency & resolution time', 'all time, avg duration to resolve', kindBars)}

		{#snippet channelBars()}
			{#if summary && summary.by_channel.length > 0}
				{@const maxChannelCount = Math.max(1, ...summary.by_channel.map((c) => c.count))}
				<div class="flex flex-col gap-1.5">
					{#each summary.by_channel as c (c.channel)}
						<div class="flex items-center gap-2 text-sm">
							<span class="w-40 truncate text-text" title={c.channel}>{c.channel}</span>
							<div class="h-3.5 flex-1 bg-bg">
								<div
									class="h-full bg-primary/70"
									style:width={`${Math.max(1, (c.count / maxChannelCount) * 100)}%`}
								></div>
							</div>
							<span class="w-12 text-right tabular-nums text-text-muted">
								{c.count.toLocaleString()}
							</span>
						</div>
					{/each}
				</div>
			{:else}
				<div class="flex h-32 items-center justify-center text-sm text-text-muted">
					No incidents recorded.
				</div>
			{/if}
		{/snippet}
		{@render chartCard('By channel', 'all time', channelBars)}
	</div>

	<div class="overflow-x-auto border border-border">
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-border bg-surface text-left text-text-muted">
					<th class="px-3 py-2 font-semibold">When</th>
					<th class="px-3 py-2 font-semibold">Kind</th>
					<th class="px-3 py-2 font-semibold">Channel</th>
					<th class="px-3 py-2 font-semibold">Status</th>
					<th class="px-3 py-2 font-semibold">Resolved by</th>
					<th class="px-3 py-2 font-semibold">Duration</th>
					<th class="px-3 py-2 font-semibold">Message</th>
				</tr>
			</thead>
			<tbody>
				{#if rows.length === 0}
					<tr>
						<td class="px-3 py-4 text-center text-text-muted" colspan="7">
							{rowsLoading ? 'Loading…' : 'No incidents recorded yet.'}
						</td>
					</tr>
				{:else}
					{#each rows as row (row.id)}
						<tr class="border-b border-border last:border-b-0 hover:bg-surface">
							<td class="px-3 py-2 whitespace-nowrap text-text-muted">
								{formatTimestamp(row.triggered_at)}
							</td>
							<td class="px-3 py-2 text-text capitalize">{formatKind(row.kind)}</td>
							<td class="px-3 py-2 text-text-muted">{row.channel_label ?? row.channel ?? '—'}</td>
							<td class="px-3 py-2 text-text-muted">
								{row.status === 'active' ? 'Active' : 'Resolved'}
							</td>
							<td class="px-3 py-2 text-text-muted">{resolvedByLabel(row.resolved_by)}</td>
							<td class="px-3 py-2 text-text-muted">{formatDuration(row.duration_s)}</td>
							<td class="max-w-xs truncate px-3 py-2 text-text-muted" title={row.operator_message ?? row.reason ?? ''}>
								{row.operator_message ?? row.reason ?? '—'}
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>
{/if}
