<script lang="ts">
	import { onMount } from 'svelte';
	import Play from '@lucide/svelte/icons/play';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import LotPartsModal from './LotPartsModal.svelte';

	type Run = {
		id: string;
		name: string;
		note: string | null;
		lot_id: string | null;
		lot_name: string | null;
		adds_to_lot: boolean;
		started_at: number;
		ended_at: number | null;
		is_current: boolean;
		pieces: number;
		distributed_pieces: number;
	};
	type Lot = {
		id: string;
		name: string;
		description: string | null;
		pieces: number;
		runs: number;
		passes: number;
	};

	let { endpointBase }: { endpointBase: string } = $props();

	const NO_LOT = '';
	const NEW_LOT = '__new__';

	let runs = $state<Run[]>([]);
	let lots = $state<Lot[]>([]);
	let error = $state<string | null>(null);

	let formOpen = $state(false);
	let editing = $state<Run | null>(null);
	let formName = $state('');
	let formLot = $state<string>(NO_LOT);
	let formNewLot = $state('');
	let formAdds = $state(true);
	let formError = $state<string | null>(null);
	let saving = $state(false);

	let lotOpen = $state(false);
	let openLot = $state<Lot | null>(null);

	const current = $derived(runs.find((r) => r.is_current) ?? null);
	const lotOptions = $derived([
		{ value: NO_LOT, label: 'No lot' },
		...lots.map((l) => ({ value: l.id, label: l.name })),
		{ value: NEW_LOT, label: 'A new lot…' }
	]);

	async function load() {
		try {
			const res = await fetch(`${endpointBase}/api/sorting-runs`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const body = await res.json();
			runs = body.runs;
			lots = body.lots;
			error = null;
		} catch (e) {
			error = `Couldn't load the runs: ${e instanceof Error ? e.message : e}`;
		}
	}

	onMount(load);

	function openStart() {
		editing = null;
		formName = '';
		formLot = current?.lot_id ?? NO_LOT;
		formNewLot = '';
		formAdds = true;
		formError = null;
		formOpen = true;
	}

	function openEdit(run: Run) {
		editing = run;
		formName = run.name;
		formLot = run.lot_id ?? NO_LOT;
		formNewLot = '';
		formAdds = run.adds_to_lot;
		formError = null;
		formOpen = true;
	}

	async function send(path: string, method: string, body: unknown) {
		const res = await fetch(`${endpointBase}${path}`, {
			method,
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		});
		const data = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
		return data;
	}

	async function save() {
		saving = true;
		formError = null;
		try {
			let lotId: string | null = formLot === NO_LOT ? null : formLot;
			if (formLot === NEW_LOT) {
				const lot = await send('/api/lots', 'POST', { name: formNewLot });
				lotId = lot.id;
			}
			const body = {
				name: formName,
				lot_id: lotId,
				adds_to_lot: lotId === null ? true : formAdds
			};
			if (editing) await send(`/api/sorting-runs/${editing.id}`, 'PATCH', body);
			else await send('/api/sorting-runs', 'POST', body);
			formOpen = false;
			await load();
		} catch (e) {
			formError = e instanceof Error ? e.message : String(e);
		} finally {
			saving = false;
		}
	}

	function when(ts: number | null): string {
		if (ts === null) return 'Now';
		return new Date(ts * 1000).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}
</script>

{#snippet lotBadge(run: Run)}
	{#if run.lot_id === null}
		<span class="text-ink-faint">None</span>
	{:else}
		<span class="flex flex-wrap items-center gap-2">
			{run.lot_name}
			{#if run.adds_to_lot}
				<Badge tone="success">Adds to the lot</Badge>
			{:else}
				<Badge tone="warning">Another pass, not counted</Badge>
			{/if}
		</span>
	{/if}
{/snippet}

<Panel
	title="Runs and lots"
	description="A run lasts across pauses and shutdowns until the next one starts. A run can add its pieces to a lot, or be another pass over pieces the lot already counted."
	flush
>
	{#snippet actions()}
		<Button size="sm" variant="primary" icon={Play} onclick={openStart}>Start a new run</Button>
	{/snippet}

	{#if error}
		<p class="px-4 py-3 text-sm text-danger-ink">{error}</p>
	{:else if runs.length === 0}
		<p class="px-4 py-3 text-sm text-ink-muted">
			No runs yet. Start one to name what you're sorting, and the lot it belongs to.
		</p>
	{:else}
		<div class="overflow-x-auto">
			<table class="data-table">
				<thead>
					<tr>
						<th>Run</th>
						<th>Lot</th>
						<th>From</th>
						<th>Until</th>
						<th class="num">Pieces</th>
						<th><span class="sr-only">Edit</span></th>
					</tr>
				</thead>
				<tbody>
					{#each runs as run (run.id)}
						<tr>
							<td>
								<span class="flex items-center gap-2">
									{run.name}
									{#if run.is_current}<Badge tone="primary" dot>Current</Badge>{/if}
								</span>
							</td>
							<td>{@render lotBadge(run)}</td>
							<td class="num text-ink-muted">{when(run.started_at)}</td>
							<td class="num text-ink-muted">{when(run.ended_at)}</td>
							<td class="num">{run.pieces.toLocaleString()}</td>
							<td class="text-right">
								<Button
									size="sm"
									variant="ghost"
									icon={Pencil}
									label={`Edit ${run.name}`}
									onclick={() => openEdit(run)}
								/>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if lots.length > 0}
		<div class="overflow-x-auto border-t border-line">
			<table class="data-table">
				<thead>
					<tr>
						<th>Lot</th>
						<th class="num">Pieces</th>
						<th class="num">Runs adding to it</th>
						<th class="num">Other passes</th>
					</tr>
				</thead>
				<tbody>
					{#each lots as lot (lot.id)}
						<tr>
							<td>
								<button
									type="button"
									class="cursor-pointer text-left text-primary-ink hover:underline"
									onclick={() => {
										openLot = lot;
										lotOpen = true;
									}}
								>
									{lot.name}
								</button>
							</td>
							<td class="num">{lot.pieces.toLocaleString()}</td>
							<td class="num text-ink-muted">{lot.runs}</td>
							<td class="num text-ink-muted">{lot.passes}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</Panel>

<Modal
	bind:open={formOpen}
	title={editing ? `Edit ${editing.name}` : 'Start a new run'}
	size="sm"
	onclose={() => (formOpen = false)}
>
	<form
		id="run-form"
		class="flex flex-col gap-4"
		onsubmit={(e) => {
			e.preventDefault();
			void save();
		}}
	>
		{#if !editing && current}
			<p class="text-sm text-ink-muted">This ends {current.name}.</p>
		{/if}
		<Field label="Name" for="run-name">
			<Input id="run-name" bind:value={formName} />
		</Field>
		<Field label="Lot" for="run-lot" info="The pieces this run puts through: a box you bought, an order, a collection.">
			<Select id="run-lot" bind:value={formLot} options={lotOptions} />
		</Field>
		{#if formLot === NEW_LOT}
			<Field label="New lot's name" for="run-new-lot">
				<Input id="run-new-lot" bind:value={formNewLot} />
			</Field>
		{/if}
		{#if formLot !== NO_LOT}
			<div class="flex items-center justify-between gap-3">
				<span id="run-adds" class="text-sm text-ink">
					Adds its pieces to the lot
					<span class="block text-ink-muted">
						Off for another pass over pieces the lot already counted.
					</span>
				</span>
				<Switch bind:checked={formAdds} labelledby="run-adds" />
			</div>
		{/if}
		{#if formError}<p class="text-sm text-danger-ink">{formError}</p>{/if}
	</form>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (formOpen = false)}>Cancel</Button>
		<Button variant="primary" type="submit" form="run-form" loading={saving}>
			{editing ? 'Save' : 'Start the run'}
		</Button>
	{/snippet}
</Modal>

<LotPartsModal bind:open={lotOpen} lot={openLot} {endpointBase} />
