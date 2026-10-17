<script lang="ts">
	import { onMount } from 'svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import IncidentCharts from '$lib/components/records/IncidentCharts.svelte';
	import IncidentTotals from '$lib/components/records/IncidentTotals.svelte';
	import {
		formatDuration,
		formatKind,
		formatTimestamp,
		resolvedByLabel,
		type IncidentRow,
		type IncidentsSummary
	} from '$lib/components/records/incidents';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Pager from '$lib/components/ui/Pager.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Skeleton from '$lib/components/ui/Skeleton.svelte';
	import { recordsBase } from '$lib/records/base';
	import { RecordsList } from '$lib/records/records-list.svelte';

	const base = recordsBase();

	// A page of incidents is about a screen: the list is a table, and a long one
	// was most of what this view showed.
	const PAGE_SIZE = 20;

	const list = new RecordsList<IncidentRow>({
		base,
		path: '/api/incidents',
		pageSize: PAGE_SIZE,
		filters: ['kind', 'status']
	});

	let summary = $state<IncidentsSummary | null>(null);
	let summaryFailed = $state(false);

	onMount(async () => {
		try {
			const res = await fetch(`${base()}/api/incidents/summary`);
			if (!res.ok) throw new Error(`${res.status}`);
			summary = (await res.json()) as IncidentsSummary;
		} catch {
			summaryFailed = true;
		}
	});

	const kindOptions = $derived([
		{ value: '', label: 'All kinds' },
		...(summary?.by_kind ?? []).map((k) => ({ value: k.kind, label: formatKind(k.kind) }))
	]);
	const statusOptions = [
		{ value: '', label: 'Any status' },
		{ value: 'active', label: 'Active' },
		{ value: 'resolved', label: 'Resolved' }
	];
</script>

<svelte:head>
	<title>Incidents - Records - Sorter</title>
</svelte:head>

{#if summary}
	<IncidentTotals {summary} />
{:else if summaryFailed}
	<Alert tone="warning">Could not load the incident data.</Alert>
{:else}
	<Skeleton class="h-24 w-full" />
{/if}

<Panel
	title="Incidents"
	description="Classification-channel clears, stepper stalls and every other operator-facing hold this machine has recorded, newest first."
	flush
>
	{#snippet actions()}
		<Select
			size="sm"
			label="Kind"
			class="w-40"
			value={list.filters.kind ?? ''}
			options={kindOptions}
			onchange={(kind) => list.setFilters({ kind: kind || null })}
		/>
		<Select
			size="sm"
			label="Status"
			class="w-36"
			value={list.filters.status ?? ''}
			options={statusOptions}
			onchange={(status) => list.setFilters({ status: status || null })}
		/>
	{/snippet}

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
				{#if list.items.length === 0}
					<tr>
						<td class="text-center text-ink-muted" colspan="7">
							{list.loading
								? 'Loading…'
								: list.failed
									? 'Could not load the incidents.'
									: 'No incidents.'}
						</td>
					</tr>
				{:else}
					{#each list.items as row (row.id)}
						<tr>
							<td class="whitespace-nowrap text-ink-muted">{formatTimestamp(row.triggered_at)}</td>
							<td>{formatKind(row.kind)}</td>
							<td class="text-ink-muted">{row.channel_label ?? row.channel ?? '—'}</td>
							<td class="text-ink-muted">{row.status === 'active' ? 'Active' : 'Resolved'}</td>
							<td class="text-ink-muted">{resolvedByLabel(row.resolved_by)}</td>
							<td class="num text-ink-muted">{formatDuration(row.duration_s)}</td>
							<td
								class="max-w-xs truncate text-ink-muted"
								title={row.operator_message ?? row.reason ?? ''}
							>
								{row.operator_message ?? row.reason ?? '—'}
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>

	{#snippet footer()}
		<div class="flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-2">
			<div class="flex items-center gap-2 text-sm text-ink-muted">
				{#if list.newer}
					<span class="num">
						{list.newer.toLocaleString()} newer {list.newer === 1 ? 'incident' : 'incidents'}
					</span>
					<Button size="sm" icon={RefreshCw} onclick={() => list.refresh()}>Show them</Button>
				{/if}
			</div>
			<Pager
				label="Incidents"
				noun="incidents"
				page={list.pageIndex + 1}
				pages={list.pageCount}
				from={list.from}
				to={list.to}
				total={list.total}
				loading={list.loading}
				jump={list.canJump}
				onpage={(n) => list.open(n - 1)}
			/>
		</div>
	{/snippet}
</Panel>

{#if summary}
	<IncidentCharts {summary} />
{/if}
