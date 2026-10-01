<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type ControlDataSummary, type ControlDataDimensionRow } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import Database from '@lucide/svelte/icons/database';

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
		if (!bytes) return '-';
		if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
		if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
		return `${(bytes / 1024).toFixed(0)} KB`;
	}
	function hrs(h: number): string {
		return h > 0 ? `${h.toFixed(1)}h` : '-';
	}
	function when(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString();
	}
	function day(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleDateString();
	}
	function mins(seconds: number): string {
		if (!seconds || seconds <= 0) return '-';
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
	<title>Control data - Hive</title>
</svelte:head>

<PageHeader
	title="Control data"
	description="Feeder capture segments synced from machines: piece positions from the vision model and the motor commands, stamped with the machine's settings when they were captured. For improving feeder control."
/>

<div class="flex flex-col gap-(--gap-panels)">
	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	{#if loading}
		<div class="flex justify-center py-12"><Spinner size={32} /></div>
	{:else if summary && summary.totals.segments === 0}
		<Panel><EmptyState icon={Database} title="No control data yet">No segments have synced.</EmptyState></Panel>
	{:else if summary}
		<section aria-label="Totals" class="overflow-hidden rounded-panel bg-surface">
			<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
				{#each [
					['Segments', num(summary.totals.segments)],
					['Records', num(summary.totals.records)],
					['Size', gb(summary.totals.bytes)],
					['Capture time', hrs(summary.totals.hours)],
					['Machines', String(summary.totals.machines)],
					['With a file', num(summary.totals.with_file)],
					['Auto-tune', num(summary.totals.autotune_session + summary.totals.autotune_background)],
					['Plain sorting', num(summary.totals.plain)]
				] as [label, value] (label)}
					<div class="border-t border-l border-line"><Stat {label} {value} /></div>
				{/each}
			</div>
		</section>
		<p class="-mt-2 text-sm text-ink-muted">
			First capture {day(summary.totals.first_started_at)}, latest {when(summary.totals.last_ended_at)}. With a file counts
			segments whose data file arrived; the machine removed the rest before they synced.
		</p>

		<Panel
			title="By machine"
			description="Session and background are segments captured while the auto-tuner was varying settings; plain is normal sorting."
			flush
		>
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Machine</th><th class="num">Segments</th><th class="num">Records</th><th class="num">Size</th><th class="num"
								>Hours</th
							><th class="num">Session</th><th class="num">Background</th><th class="num">Plain</th><th>Setups and modes</th
							><th>First</th><th>Latest</th>
						</tr>
					</thead>
					<tbody>
						{#each summary.machines as m (m.machine_id)}
							<tr>
								<td class="whitespace-nowrap">
									<a href={`/machines/${m.machine_id}`} class="font-medium text-ink hover:underline">{m.name}</a>
									{#if m.owner_email}<div class="text-ink-muted">{m.owner_email}</div>{/if}
								</td>
								<td class="num">{num(m.segments)}</td>
								<td class="num">{num(m.records)}</td>
								<td class="num whitespace-nowrap text-ink-muted">{gb(m.bytes)}</td>
								<td class="num">{hrs(m.hours)}</td>
								<td class="num text-ink-muted">{num(m.autotune_session)}</td>
								<td class="num text-ink-muted">{num(m.autotune_background)}</td>
								<td class="num text-ink-muted">{num(m.plain)}</td>
								<td class="text-ink-muted"
									>{[...m.machine_setups, ...m.feeder_modes, ...m.classification_modes].join(', ') || '-'}</td
								>
								<td class="whitespace-nowrap text-ink-muted">{day(m.first_started_at)}</td>
								<td class="whitespace-nowrap text-ink-muted">{when(m.last_ended_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>

		<div class="grid gap-(--gap-panels) lg:grid-cols-2">
			{#each dimensionEntries as dim (dim.key)}
				<!-- min-w-0, or the grid track takes the widest cell and the table never scrolls. -->
				<div class="min-w-0">
					<Panel title={dim.label} flush>
						<div class="overflow-x-auto">
							<table class="data-table">
								<thead>
									<tr><th>Value</th><th class="num">Segments</th><th class="num">Records</th><th class="num">Hours</th><th class="num">Machines</th></tr>
								</thead>
								<tbody>
									{#each dim.rows as row (row.value ?? '__none__')}
										<tr>
											<td class={row.value ? '' : 'text-ink-muted'}
												>{row.value ?? (dim.key === 'autotune_mode' ? 'Off, plain sorting' : 'Unknown')}</td
											>
											<td class="num">{num(row.segments)}</td>
											<td class="num text-ink-muted">{num(row.records)}</td>
											<td class="num text-ink-muted">{hrs(row.hours)}</td>
											<td class="num">{row.machines}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</Panel>
				</div>
			{/each}
		</div>

		<Panel title="Recent segments" flush>
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Machine</th><th class="num">Segment</th><th>Started</th><th class="num">Length</th><th class="num">Records</th><th class="num"
								>Size</th
							><th>Feeder mode</th><th>Auto-tune</th><th>File</th>
						</tr>
					</thead>
					<tbody>
						{#each summary.recent as seg (`${seg.machine_id}:${seg.local_id}`)}
							<tr>
								<td class="whitespace-nowrap">{seg.machine_name}</td>
								<td class="num text-ink-muted">{seg.local_id}</td>
								<td class="whitespace-nowrap text-ink-muted">{when(seg.started_at)}</td>
								<td class="num text-ink-muted">{mins(seg.duration_s)}</td>
								<td class="num">{num(seg.records)}</td>
								<td class="num whitespace-nowrap text-ink-muted">{gb(seg.bytes)}</td>
								<td class="whitespace-nowrap text-ink-muted">{seg.feeder_mode ?? '-'}</td>
								<td class="whitespace-nowrap text-ink-muted">{seg.autotune_mode ?? '-'}</td>
								<td>
									{#if seg.has_file}<Badge tone="success">Synced</Badge>{:else}<Badge tone="danger">Missing</Badge>{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>
	{/if}
</div>
