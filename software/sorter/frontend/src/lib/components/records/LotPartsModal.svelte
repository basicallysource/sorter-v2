<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';

	type LotRun = { id: string; name: string; adds_to_lot: boolean; started_at: number };
	type LotPart = {
		part_id: string;
		part_name: string | null;
		color_id: string | null;
		color_name: string | null;
		counts: Record<string, number>;
		in_lot: number;
	};

	let {
		open = $bindable(false),
		lot,
		endpointBase
	}: {
		open?: boolean;
		lot: { id: string; name: string } | null;
		endpointBase: string;
	} = $props();

	const PAGE = 100;

	let runs = $state<LotRun[]>([]);
	let parts = $state<LotPart[]>([]);
	let error = $state<string | null>(null);
	let loading = $state(false);
	let againOnly = $state(false);
	let shown = $state(PAGE);

	const seenAgain = $derived(parts.filter((p) => Object.keys(p.counts).length > 1));
	const rows = $derived((againOnly ? seenAgain : parts).slice(0, shown));
	const rowCount = $derived(againOnly ? seenAgain.length : parts.length);

	$effect(() => {
		if (open && lot) void load(lot.id);
	});

	async function load(lotId: string) {
		loading = true;
		error = null;
		shown = PAGE;
		try {
			const res = await fetch(`${endpointBase}/api/lots/${lotId}/parts`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const body = await res.json();
			runs = body.runs;
			parts = body.parts;
		} catch (e) {
			error = `Couldn't load the lot: ${e instanceof Error ? e.message : e}`;
		} finally {
			loading = false;
		}
	}
</script>

<Modal bind:open title={lot ? lot.name : 'Lot'} size="lg" onclose={() => (open = false)}>
	<div class="flex flex-col gap-3">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<p class="text-sm text-ink-muted">
				Each part and color, counted in each of the lot's runs.
				{seenAgain.length.toLocaleString()} of {parts.length.toLocaleString()} came through more than once.
			</p>
			<div class="flex items-center gap-2">
				<span id="lot-again-only" class="text-sm text-ink">Only parts seen more than once</span>
				<Switch bind:checked={againOnly} labelledby="lot-again-only" />
			</div>
		</div>

		{#if error}
			<p class="text-sm text-danger-ink">{error}</p>
		{:else if loading}
			<p class="text-sm text-ink-muted">Loading the lot</p>
		{:else}
			<div class="max-h-[60vh] overflow-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Part</th>
							<th>Color</th>
							{#each runs as run (run.id)}
								<th class="num">
									{run.name}
									<span class="block font-normal text-ink-muted">
										{run.adds_to_lot ? 'adds to the lot' : 'another pass'}
									</span>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each rows as part (`${part.part_id}-${part.color_id}`)}
							<tr>
								<td>
									{part.part_name ?? part.part_id}
									<span class="block text-ink-muted">{part.part_id}</span>
								</td>
								<td>{part.color_name ?? part.color_id ?? 'Unknown'}</td>
								{#each runs as run (run.id)}
									<td class="num {part.counts[run.id] ? '' : 'text-ink-faint'}">
										{part.counts[run.id] ?? 0}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if shown < rowCount}
				<div class="flex justify-center">
					<Button size="sm" onclick={() => (shown += PAGE)}>
						Show {Math.min(PAGE, rowCount - shown)} more ({(rowCount - shown).toLocaleString()} left)
					</Button>
				</div>
			{/if}
		{/if}
	</div>
</Modal>
