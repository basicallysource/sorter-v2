<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type FleetMachine, type FleetMachineStats } from '$lib/api';
	import { goto } from '$app/navigation';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Cpu from '@lucide/svelte/icons/cpu';
	import AnalyticsDashboard from '$lib/components/charts/AnalyticsDashboard.svelte';

	let machines = $state<FleetMachine[]>([]);
	let stats = $state<Record<string, FleetMachineStats>>({});
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
			const [m, s] = await Promise.all([api.getAllMachines(), api.getAllMachineStats()]);
			stats = s;
			// Busiest machines first — the fleet view is about who's sorting.
			machines = m.sort((a, b) => (stats[b.id]?.pieces_seen ?? 0) - (stats[a.id]?.pieces_seen ?? 0));
		} catch (e: any) {
			error = e.error || 'Failed to load machines';
		} finally {
			loading = false;
		}
	}

	const EMPTY: FleetMachineStats = {
		pieces_seen: 0, distributed: 0, classified: 0, unique_parts: 0, unique_colors: 0,
		first_seen: null, last_seen: null, active_seconds: 0, overall_ppm: 0, ontime_pct: 0
	};

	function statOf(id: string): FleetMachineStats {
		return stats[id] ?? EMPTY;
	}

	function num(n: number): string {
		return Math.round(n).toLocaleString();
	}
	function ppm(n: number): string {
		return n > 0 ? n.toFixed(1) : '-';
	}
	function pct(n: number): string {
		return n > 0 ? `${n.toFixed(1)}%` : '-';
	}
	function hours(seconds: number): string {
		if (!seconds || seconds <= 0) return '-';
		return `${(seconds / 3600).toFixed(1)}h`;
	}
	function when(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleDateString();
	}

	const fleetPieces = $derived(machines.reduce((sum, m) => sum + statOf(m.id).pieces_seen, 0));
</script>

<svelte:head>
	<title>All machines - Hive</title>
</svelte:head>

<PageHeader title="All machines">
	{#snippet actions()}
		<span class="num text-sm text-ink-muted">{machines.length} machines, {num(fleetPieces)} pieces sorted</span>
	{/snippet}
</PageHeader>

<div class="flex flex-col gap-(--gap-panels)">
	<section class="flex flex-col gap-(--gap-panels)">
		<h2 class="text-base font-semibold text-ink">Fleet analytics</h2>
		<AnalyticsDashboard scope="all" />
	</section>

	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	{#if loading}
		<div class="flex justify-center py-12"><Spinner size={32} /></div>
	{:else if machines.length === 0}
		<Panel><EmptyState icon={Cpu} title="No machines yet">No machine has connected to this Hive.</EmptyState></Panel>
	{:else}
		<Panel
			title="Machines"
			description="Pieces a minute and on time come from the synced pieces' times, not each machine's own clock."
			flush
		>
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Machine</th><th>Owner</th><th class="num">Pieces</th><th class="num">Distributed</th><th class="num"
								>A minute</th
							><th class="num">On time</th><th class="num">Sorting</th><th class="num">Parts</th><th class="num">Colors</th><th
								>Last seen</th
							>
						</tr>
					</thead>
					<tbody>
						{#each machines as machine (machine.id)}
							{@const s = statOf(machine.id)}
							<tr class={machine.archived_at ? 'opacity-50' : ''}>
								<td>
									<div class="flex items-center gap-2 whitespace-nowrap">
										<a href={`/machines/${machine.id}`} class="font-medium text-ink hover:underline">{machine.name}</a>
										{#if machine.archived_at}<Badge>Archived</Badge>{:else if !machine.is_active}<Badge tone="danger">Inactive</Badge>{/if}
									</div>
								</td>
								<td class="whitespace-nowrap">
									<div>{machine.owner_display_name || '-'}</div>
									<div class="text-ink-muted">{machine.owner_email || ''}</div>
								</td>
								<td class="num">{num(s.pieces_seen)}</td>
								<td class="num text-ink-muted">{num(s.distributed)}</td>
								<td class="num">{ppm(s.overall_ppm)}</td>
								<td class="num text-ink-muted">{pct(s.ontime_pct)}</td>
								<td class="num text-ink-muted">{hours(s.active_seconds)}</td>
								<td class="num text-ink-muted">{num(s.unique_parts)}</td>
								<td class="num text-ink-muted">{num(s.unique_colors)}</td>
								<td class="whitespace-nowrap text-ink-muted">{when(machine.last_seen_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>
	{/if}
</div>
