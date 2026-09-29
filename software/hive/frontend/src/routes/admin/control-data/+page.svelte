<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type ControlDataSummary, type ControlDataDimensionRow } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';

	let summary = $state<ControlDataSummary | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		load();
	});

	async function load() {
		loading = true;
		error = null;
		try {
			summary = await api.getControlDataSummary();
		} catch (e: any) {
			error = e.error || 'Failed to load control data summary';
		} finally {
			loading = false;
		}
	}

	function num(n: number): string {
		return Math.round(n).toLocaleString();
	}
	function gb(bytes: number): string {
		if (!bytes) return '—';
		if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
		if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
		return `${(bytes / 1024).toFixed(0)} KB`;
	}
	function hrs(h: number): string {
		return h > 0 ? `${h.toFixed(1)}h` : '—';
	}
	function when(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleString();
	}
	function day(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleDateString();
	}
	function mins(seconds: number): string {
		if (!seconds || seconds <= 0) return '—';
		return `${(seconds / 60).toFixed(1)}m`;
	}

	const DIMENSION_LABELS: Record<string, string> = {
		machine_setup: 'Machine setup',
		feeder_mode: 'Feeder mode',
		classification_mode: 'Classification mode',
		autotune_mode: 'Auto-tune mode'
	};

	const dimensionEntries = $derived(
		summary
			? Object.entries(DIMENSION_LABELS).map(([key, label]) => ({
					key,
					label,
					rows: (summary!.dimensions[key] ?? []) as ControlDataDimensionRow[]
				}))
			: []
	);
</script>

<svelte:head>
	<title>Control Data - Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<h1 class="text-2xl font-bold text-ink">Control Data</h1>
	{#if summary}
		<span class="text-sm text-ink-muted">
			{num(summary.totals.segments)} segments · {num(summary.totals.records)} records ·
			{gb(summary.totals.bytes)} · {summary.totals.machines} machines
		</span>
	{/if}
</div>

<p class="mb-6 text-sm text-ink-muted">
	Feeder-dynamics capture segments synced from machines: piece positions from the vision model plus
	motor commands, stamped with the machine's settings at capture time. Used to improve feeder
	control.
</p>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary-ink">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner size={32} />
	</div>
{:else if summary && summary.totals.segments === 0}
	<div class="border border-line bg-surface p-8 text-center text-sm text-ink-muted">
		No control data segments synced yet.
	</div>
{:else if summary}
	<section class="mb-8">
		<h2 class="mb-3 text-lg font-semibold text-ink">Totals</h2>
		<div class="grid grid-cols-2 gap-px border border-line bg-border sm:grid-cols-4 lg:grid-cols-8">
			{#each [
				['Segments', num(summary.totals.segments)],
				['Records', num(summary.totals.records)],
				['Volume', gb(summary.totals.bytes)],
				['Capture time', hrs(summary.totals.hours)],
				['Machines', String(summary.totals.machines)],
				['With file', num(summary.totals.with_file)],
				['Auto-tune', num(summary.totals.autotune_session + summary.totals.autotune_background)],
				['Plain sorting', num(summary.totals.plain)]
			] as [label, value]}
				<div class="bg-surface p-3">
					<p class="text-xs uppercase tracking-wider text-ink-muted">{label}</p>
					<p class="mt-1 text-lg font-semibold text-ink tabular-nums">{value}</p>
				</div>
			{/each}
		</div>
		<p class="mt-2 text-xs text-ink-muted">
			First capture {day(summary.totals.first_started_at)} · latest {when(summary.totals.last_ended_at)}
			· "with file" counts segments whose data file made it up (the rest were evicted on the machine
			before syncing).
		</p>
	</section>

	<section class="mb-8">
		<h2 class="mb-3 text-lg font-semibold text-ink">By machine</h2>
		<div class="overflow-x-auto border border-line bg-surface">
			<table class="min-w-full divide-y divide-line">
				<thead class="bg-well">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Machine</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Segments</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Records</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Volume</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Hours</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Session</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Background</th>
						<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Plain</th>
						<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Setups / modes</th>
						<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">First</th>
						<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Latest</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-line">
					{#each summary.machines as m (m.machine_id)}
						<tr class="hover:bg-hover">
							<td class="whitespace-nowrap px-4 py-3">
								<a href={`/machines/${m.machine_id}`} class="text-sm font-medium text-primary-ink hover:underline">{m.name}</a>
								{#if m.owner_email}
									<p class="text-xs text-ink-muted">{m.owner_email}</p>
								{/if}
							</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink tabular-nums">{num(m.segments)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink tabular-nums">{num(m.records)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink-muted tabular-nums">{gb(m.bytes)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink tabular-nums">{hrs(m.hours)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink-muted tabular-nums">{num(m.autotune_session)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink-muted tabular-nums">{num(m.autotune_background)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-ink-muted tabular-nums">{num(m.plain)}</td>
							<td class="px-4 py-3 text-xs text-ink-muted">
								{[...m.machine_setups, ...m.feeder_modes, ...m.classification_modes].join(', ') || '—'}
							</td>
							<td class="whitespace-nowrap px-4 py-3 text-sm text-ink-muted">{day(m.first_started_at)}</td>
							<td class="whitespace-nowrap px-4 py-3 text-sm text-ink-muted">{when(m.last_ended_at)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="mt-2 text-xs text-ink-muted">
			Session / Background = segments captured while the pulse-perception auto-tuner was varying
			parameters; Plain = normal sorting with fixed settings.
		</p>
	</section>

	<section class="mb-8">
		<h2 class="mb-3 text-lg font-semibold text-ink">By dimension</h2>
		<div class="grid gap-6 lg:grid-cols-2">
			{#each dimensionEntries as dim (dim.key)}
				<!-- min-w-0: without it the grid track sizes to the widest table cell
				     and the overflow-x-auto wrapper below never gets to scroll. -->
				<div class="min-w-0">
					<h3 class="mb-2 text-sm font-semibold text-ink">{dim.label}</h3>
					<div class="overflow-x-auto border border-line bg-surface">
						<table class="min-w-full divide-y divide-line">
							<thead class="bg-well">
								<tr>
									<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Value</th>
									<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Segments</th>
									<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Records</th>
									<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Hours</th>
									<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Machines</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-line">
								{#each dim.rows as row (row.value ?? '__none__')}
									<tr class="hover:bg-hover">
										<td class="px-4 py-2 text-sm {row.value ? 'text-ink' : 'text-ink-muted italic'}">
											{row.value ?? (dim.key === 'autotune_mode' ? 'off (plain sorting)' : 'unknown')}
										</td>
										<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink tabular-nums">{num(row.segments)}</td>
										<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink-muted tabular-nums">{num(row.records)}</td>
										<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink-muted tabular-nums">{hrs(row.hours)}</td>
										<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink tabular-nums">{row.machines}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/each}
		</div>
	</section>

	<section class="mb-8">
		<h2 class="mb-3 text-lg font-semibold text-ink">Recent segments</h2>
		<div class="overflow-x-auto border border-line bg-surface">
			<table class="min-w-full divide-y divide-line">
				<thead class="bg-well">
					<tr>
						<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Machine</th>
						<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Seg #</th>
						<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Started</th>
						<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Length</th>
						<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Records</th>
						<th class="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-ink-muted">Size</th>
						<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Feeder mode</th>
						<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">Auto-tune</th>
						<th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted">File</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-line">
					{#each summary.recent as seg (`${seg.machine_id}:${seg.local_id}`)}
						<tr class="hover:bg-hover">
							<td class="whitespace-nowrap px-4 py-2 text-sm text-ink">{seg.machine_name}</td>
							<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink-muted tabular-nums">{seg.local_id}</td>
							<td class="whitespace-nowrap px-4 py-2 text-sm text-ink-muted">{when(seg.started_at)}</td>
							<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink-muted tabular-nums">{mins(seg.duration_s)}</td>
							<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink tabular-nums">{num(seg.records)}</td>
							<td class="whitespace-nowrap px-4 py-2 text-right text-sm text-ink-muted tabular-nums">{gb(seg.bytes)}</td>
							<td class="whitespace-nowrap px-4 py-2 text-sm text-ink-muted">{seg.feeder_mode ?? '—'}</td>
							<td class="whitespace-nowrap px-4 py-2 text-sm text-ink-muted">{seg.autotune_mode ?? '—'}</td>
							<td class="whitespace-nowrap px-4 py-2 text-sm {seg.has_file ? 'text-ink-muted' : 'text-danger-ink'}">
								{seg.has_file ? 'synced' : 'missing'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>
{/if}
