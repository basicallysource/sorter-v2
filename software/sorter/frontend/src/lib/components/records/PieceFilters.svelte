<script lang="ts">
	import { onDestroy, onMount, untrack } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import { categoryLabel } from '$lib/components/bins/pieces';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import type { PieceSummary } from '$lib/pieces';
	import {
		pieceFilterKeys,
		reviewedOptions,
		sortOptions,
		statusOptions
	} from '$lib/records/piece-filters';
	import type { RecordsList } from '$lib/records/records-list.svelte';
	import { getBinChoices, type BinChoice } from '$lib/training/api';

	// What the Pieces list is narrowed to: a search over what a piece is called,
	// and the filters. They are in the address (the list reads them there), so
	// Back and a link show the same list; typing waits for a pause before it asks
	// the machine.
	let { list, base }: { list: RecordsList<PieceSummary>; base: () => string } = $props();

	const filters = $derived(list.filters);
	const filtering = $derived(Object.keys(filters).length > 0);

	let search = $state(untrack(() => list.filters.q ?? ''));
	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	function searchNow() {
		clearTimeout(searchTimer);
		const q = search.trim();
		if (q !== (list.filters.q ?? '')) list.setFilters({ q: q || null });
	}

	function searchSoon() {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(searchNow, 300);
	}

	// Back and Forward put the address's search in the field.
	$effect(() => {
		const q = filters.q ?? '';
		untrack(() => {
			if (q !== search.trim()) search = q;
		});
	});
	onDestroy(() => clearTimeout(searchTimer));

	function clear() {
		search = '';
		list.setFilters(Object.fromEntries(pieceFilterKeys.map((key) => [key, null])));
	}

	// The runs and lots, and the bins, a piece can be filtered by.
	type Run = { id: string; name: string; pieces: number };
	let runs = $state<Run[]>([]);
	let lots = $state<Run[]>([]);
	let bins = $state<BinChoice[]>([]);

	onMount(() => {
		void fetch(`${base()}/api/sorting-runs`)
			.then((res) => (res.ok ? res.json() : null))
			.then((body) => {
				runs = body?.runs ?? [];
				lots = body?.lots ?? [];
			})
			.catch(() => {});
		void getBinChoices(base())
			.then((choices) => (bins = choices))
			.catch(() => {});
	});

	const runOptions = $derived([
		{ value: '', label: 'Any run or lot' },
		...lots.map((l) => ({
			value: `lot:${l.id}`,
			label: `Lot: ${l.name}`,
			hint: l.pieces.toLocaleString()
		})),
		...runs.map((r) => ({
			value: `run:${r.id}`,
			label: `Run: ${r.name}`,
			hint: r.pieces.toLocaleString()
		}))
	]);
	const runValue = $derived(
		filters.run ? `run:${filters.run}` : filters.lot ? `lot:${filters.lot}` : ''
	);

	function chooseRun(value: string) {
		const at = value.indexOf(':');
		const [kind, id] = at < 0 ? ['', ''] : [value.slice(0, at), value.slice(at + 1)];
		list.setFilters({ run: kind === 'run' ? id : null, lot: kind === 'lot' ? id : null });
	}

	// A bin as the pieces' rows write it (L0 · S1 · B1), with what it takes.
	const binOptions = $derived([
		{ value: '', label: 'Any bin' },
		...bins.map((b) => {
			const categories = categoryLabel(b.categoryIds);
			return {
				value: `${b.layer}-${b.section}-${b.bin}`,
				label: `L${b.layer} · S${b.section} · B${b.bin}${categories ? ` · ${categories}` : ''}`
			};
		})
	]);
</script>

<Panel flush>
	<div class="flex flex-col gap-2 p-3">
		<div class="flex flex-wrap items-center gap-2">
			<Input
				bind:value={search}
				size="sm"
				class="w-full sm:w-80"
				placeholder="Search part number, name, color or piece id"
				aria-label="Search the pieces"
				autocomplete="off"
				spellcheck={false}
				oninput={searchSoon}
				onkeydown={(event: KeyboardEvent) => event.key === 'Enter' && searchNow()}
			>
				{#snippet end()}
					{#if search}
						<Button
							size="sm"
							variant="ghost"
							icon={X}
							label="Clear the search"
							onclick={() => {
								search = '';
								searchNow();
							}}
						/>
					{/if}
				{/snippet}
			</Input>
			<Select
				size="sm"
				label="Status"
				class="min-w-[9rem] flex-1 sm:w-36 sm:flex-none"
				value={filters.status ?? ''}
				options={statusOptions}
				onchange={(status) => list.setFilters({ status: status || null })}
			/>
			<Select
				size="sm"
				label="Run or lot"
				class="min-w-[9rem] flex-1 sm:w-48 sm:flex-none"
				value={runValue}
				options={runOptions}
				onchange={chooseRun}
			/>
			<Select
				size="sm"
				label="Bin"
				class="min-w-[9rem] flex-1 sm:w-44 sm:flex-none"
				value={filters.bin ?? ''}
				options={binOptions}
				onchange={(bin) => list.setFilters({ bin: bin || null })}
			/>
		</div>
		<div class="flex flex-wrap items-center gap-2">
			<label
				class="flex min-w-[9rem] flex-1 items-center gap-2 text-sm text-ink-muted sm:flex-none"
			>
				From
				<Input
					type="date"
					size="sm"
					class="min-w-0 flex-1 sm:w-40 sm:flex-none"
					value={filters.from ?? ''}
					max={filters.to}
					onchange={(event: Event) =>
						list.setFilters({ from: (event.currentTarget as HTMLInputElement).value || null })}
				/>
			</label>
			<label
				class="flex min-w-[9rem] flex-1 items-center gap-2 text-sm text-ink-muted sm:flex-none"
			>
				To
				<Input
					type="date"
					size="sm"
					class="min-w-0 flex-1 sm:w-40 sm:flex-none"
					value={filters.to ?? ''}
					min={filters.from}
					onchange={(event: Event) =>
						list.setFilters({ to: (event.currentTarget as HTMLInputElement).value || null })}
				/>
			</label>
			<Select
				size="sm"
				label="Review"
				class="min-w-[9rem] flex-1 sm:w-36 sm:flex-none"
				value={filters.reviewed ?? ''}
				options={reviewedOptions}
				onchange={(reviewed) => list.setFilters({ reviewed: reviewed || null })}
			/>
			<Select
				size="sm"
				label="Order"
				class="min-w-[9rem] flex-1 sm:w-36 sm:flex-none"
				value={filters.sort ?? ''}
				options={sortOptions}
				onchange={(sort) => list.setFilters({ sort: sort || null })}
			/>
			{#if filtering}
				<Button size="sm" variant="ghost" icon={X} onclick={clear}>Clear filters</Button>
			{/if}
		</div>
	</div>
</Panel>
