<script lang="ts">
	import { onMount } from 'svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import BarList from './BarList.svelte';
	import SeriesChart from './SeriesChart.svelte';

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

	// "exit_stuck" reads "Exit stuck": sentence case, like every other label.
	function formatKind(kind: string): string {
		const words = kind.replace(/_/g, ' ');
		return words.charAt(0).toUpperCase() + words.slice(1);
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

</script>

<section class="flex flex-col gap-3">
	<div>
		<h2 class="text-base font-semibold text-ink">Incidents</h2>
		<p class="mt-0.5 text-sm text-ink-muted">
			Classification-channel clears, stepper stalls and every other operator-facing hold this
			machine has recorded.
		</p>
	</div>

	{#if summary === null}
		{#if error}
			<Alert tone="warning">Could not load the incident data.</Alert>
		{:else}
			<Skeleton class="h-24 w-full" />
		{/if}
	{:else}
		<Panel flush>
			<div class="grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
				<div class="bg-surface"><Stat label="Total incidents" value={summary.total.toLocaleString()} /></div>
				<div class="bg-surface">
					<Stat
						label="Currently active"
						value={summary.active.toLocaleString()}
						hint={summary.active > 0 ? 'awaiting the operator' : undefined}
						tone={summary.active > 0 ? 'warning' : undefined}
					/>
				</div>
				<div class="bg-surface"><Stat label="Distinct kinds" value={summary.by_kind.length.toLocaleString()} /></div>
				<div class="bg-surface">
					<Stat
						label="Most frequent"
						value={summary.by_kind[0] ? formatKind(summary.by_kind[0].kind) : '—'}
						hint={summary.by_kind[0] ? `${summary.by_kind[0].count.toLocaleString()} times` : undefined}
					/>
				</div>
			</div>
		</Panel>

		<div class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-2">
			<Panel title="Incidents per day" description="Last year.">
				<SeriesChart
					points={summary.by_day.map((p) => ({ date: p.date, value: p.count }))}
					kind="bar"
					color="var(--danger)"
				/>
			</Panel>
			<Panel title="By channel" description="All time.">
				<BarList
					empty="No incidents recorded."
					rows={summary.by_channel.map((c) => ({ key: c.channel, label: c.channel, count: c.count }))}
				/>
			</Panel>
			<Panel
				title="Frequency and resolution time"
				description="All time; the average time to resolve."
				class="lg:col-span-2"
			>
				<BarList
					tone="danger"
					labelWidth="sm:w-40"
					empty="No incidents recorded."
					rows={summary.by_kind.map((k) => ({
						key: k.kind,
						label: formatKind(k.kind),
						count: k.count,
						note: `${formatDuration(k.avg_duration_s)} avg`
					}))}
				/>
			</Panel>
		</div>
	{/if}

	<Panel title="Recent incidents" flush>
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>When</th>
						<th>Kind</th>
						<th>Channel</th>
						<th>Status</th>
						<th>Resolved by</th>
						<th class="num">Duration</th>
						<th>Message</th>
					</tr>
				</thead>
				<tbody>
					{#if rows.length === 0}
						<tr>
							<td class="text-center text-ink-muted" colspan="7">
								{rowsLoading ? 'Loading…' : 'No incidents recorded yet.'}
							</td>
						</tr>
					{:else}
						{#each rows as row (row.id)}
							<tr>
								<td class="whitespace-nowrap text-ink-muted">{formatTimestamp(row.triggered_at)}</td>
								<td>{formatKind(row.kind)}</td>
								<td class="text-ink-muted">{row.channel_label ?? row.channel ?? '—'}</td>
								<td class="text-ink-muted">{row.status === 'active' ? 'Active' : 'Resolved'}</td>
								<td class="text-ink-muted">{resolvedByLabel(row.resolved_by)}</td>
								<td class="num text-ink-muted">{formatDuration(row.duration_s)}</td>
								<td class="max-w-xs truncate text-ink-muted" title={row.operator_message ?? row.reason ?? ''}>
									{row.operator_message ?? row.reason ?? '—'}
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
	</Panel>
</section>
