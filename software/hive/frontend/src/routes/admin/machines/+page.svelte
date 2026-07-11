<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type FleetMachine, type FleetMachineStats } from '$lib/api';
	import { goto } from '$app/navigation';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

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
		return n > 0 ? n.toFixed(1) : '—';
	}
	function pct(n: number): string {
		return n > 0 ? `${n.toFixed(1)}%` : '—';
	}
	function hours(seconds: number): string {
		if (!seconds || seconds <= 0) return '—';
		return `${(seconds / 3600).toFixed(1)}h`;
	}
	function when(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleDateString();
	}

	const fleetPieces = $derived(machines.reduce((sum, m) => sum + statOf(m.id).pieces_seen, 0));
</script>

<svelte:head>
	<title>All Machines - Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<h1 class="text-2xl font-bold text-text">All Machines</h1>
	<span class="text-sm text-text-muted">
		{machines.length} machines · {num(fleetPieces)} pieces sorted
	</span>
</div>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

{#if loading}
	<div class="flex justify-center py-12">
		<Spinner />
	</div>
{:else if machines.length === 0}
	<div class="border border-border bg-surface p-8 text-center text-sm text-text-muted">
		No machines connected to this Hive yet.
	</div>
{:else}
	<div class="overflow-x-auto border border-border bg-surface">
		<table class="min-w-full divide-y divide-border">
			<thead class="bg-bg">
				<tr>
					<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Machine</th>
					<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Owner</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Pieces</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Distributed</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">PPM</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">On-time</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Sorted</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Parts</th>
					<th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Colors</th>
					<th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Last seen</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each machines as machine (machine.id)}
					{@const s = statOf(machine.id)}
					<tr class="hover:bg-bg {machine.archived_at ? 'opacity-50' : ''}">
						<td class="whitespace-nowrap px-4 py-3">
							<div class="flex items-center gap-2">
								<a
										href={`/machines/${machine.id}`}
										class="text-sm font-medium text-primary hover:underline"
									>{machine.name}</a>
								{#if machine.archived_at}
									<Badge text="Archived" variant="neutral" />
								{:else if !machine.is_active}
									<Badge text="Inactive" variant="danger" />
								{/if}
							</div>
						</td>
						<td class="whitespace-nowrap px-4 py-3">
							<p class="text-sm text-text">{machine.owner_display_name || '—'}</p>
							<p class="text-xs text-text-muted">{machine.owner_email || ''}</p>
						</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text tabular-nums">{num(s.pieces_seen)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text-muted tabular-nums">{num(s.distributed)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text tabular-nums">{ppm(s.overall_ppm)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text-muted tabular-nums">{pct(s.ontime_pct)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text-muted tabular-nums">{hours(s.active_seconds)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text-muted tabular-nums">{num(s.unique_parts)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-right text-sm text-text-muted tabular-nums">{num(s.unique_colors)}</td>
						<td class="whitespace-nowrap px-4 py-3 text-sm text-text-muted">{when(machine.last_seen_at)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<p class="mt-3 text-xs text-text-muted">
		PPM and on-time % are derived from synced piece timestamps (active sorting inferred from
		piece density), not the machine's exact powered/sorted clock.
	</p>
{/if}
