<script lang="ts">
	// Pick the true mold for a piece: confirm what the machine guessed, search the
	// catalog for the right one, or say it can't be told. Mirrors the True color
	// picker next to it — the machine's guess is pinned at the top as the thing to
	// accept or replace, and every choice commits immediately.
	import { api, type PartSummary, type ProfileCatalogCategory, type ProfileCatalogSearchResult } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Ban from '@lucide/svelte/icons/ban';
	import Check from '@lucide/svelte/icons/check';

	let {
		predictedPart,
		selectedPart,
		cantTell,
		saving = false,
		onPick,
		onCantTell,
		onClear
	}: {
		predictedPart: PartSummary | null;
		selectedPart: PartSummary | null;
		cantTell: boolean;
		saving?: boolean;
		onPick: (partNum: string) => void;
		onCantTell: () => void;
		onClear: () => void;
	} = $props();

	let query = $state('');
	let catId = $state<number | ''>('');
	let results = $state<ProfileCatalogSearchResult[]>([]);
	let categories = $state<ProfileCatalogCategory[]>([]);
	let searching = $state(false);
	let searched = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	const selectedNum = $derived(selectedPart?.part_num ?? null);
	const predictedNum = $derived(predictedPart?.part_num ?? null);
	// The machine's guess is only worth pinning while it's still on offer —
	// once it IS the answer the selected row below says so.
	const showPredicted = $derived(predictedPart != null && predictedNum !== selectedNum);

	$effect(() => {
		void (async () => {
			try {
				const res = await api.profileCatalogCategories();
				categories = res.results;
			} catch {
				categories = [];
			}
		})();
	});

	function scheduleSearch() {
		if (debounceTimer) clearTimeout(debounceTimer);
		const q = query.trim();
		if (!q && catId === '') {
			results = [];
			searched = false;
			return;
		}
		debounceTimer = setTimeout(() => void runSearch(), 300);
	}

	async function runSearch() {
		const q = query.trim();
		if (!q && catId === '') return;
		searching = true;
		searched = true;
		try {
			const res = await api.searchProfileCatalogParts({
				q,
				cat_id: catId === '' ? undefined : catId,
				limit: 30
			});
			results = res.results;
		} catch {
			results = [];
		} finally {
			searching = false;
		}
	}

	function pick(partNum: string) {
		query = '';
		results = [];
		searched = false;
		onPick(partNum);
	}
</script>

{#snippet partRow(
	part: { part_num: string; name: string | null; part_img_url: string | null; category: string | null },
	kind: 'predicted' | 'selected' | 'result'
)}
	<div class="flex min-w-0 flex-1 items-center gap-2.5 text-left">
		{#if part.part_img_url}
			<img src={part.part_img_url} alt="" class="size-10 shrink-0 object-contain" />
		{:else}
			<div class="flex size-10 shrink-0 items-center justify-center rounded-item bg-well text-sm text-ink-faint">-</div>
		{/if}
		<div class="min-w-0 flex-1">
			<div class="truncate text-sm text-ink">{part.name ?? part.part_num}</div>
			<div class="truncate text-sm text-ink-muted">
				<span class="font-mono">{part.part_num}</span>{part.category ? `, ${part.category}` : ''}
			</div>
		</div>
		{#if kind === 'selected'}<Check size={16} class="shrink-0 text-primary-ink" />{/if}
	</div>
{/snippet}

<div class="flex flex-col gap-3">
	<button
		type="button"
		onclick={onCantTell}
		disabled={saving}
		aria-pressed={cantTell}
		class="flex w-full items-center gap-2 rounded-item px-3 py-2 text-left text-sm disabled:opacity-45 {cantTell
			? 'bg-primary-soft font-medium text-primary-ink'
			: 'bg-well text-ink-muted hover:bg-hover'}"
	>
		<Ban size={16} class="shrink-0" />
		<span class="flex-1">I can't tell the part</span>
		{#if cantTell}<Check size={16} class="shrink-0" />{/if}
	</button>

	{#if selectedPart}
		<div>
			<div class="label mb-1.5">Your answer</div>
			<div class="flex items-center gap-2 rounded-item bg-primary-soft px-3 py-2">
				{@render partRow(
					{
						part_num: selectedPart.part_num,
						name: selectedPart.name,
						part_img_url: selectedPart.part_img_url,
						category: selectedPart.category_name
					},
					'selected'
				)}
				<Button size="sm" variant="ghost" disabled={saving} onclick={onClear}>Clear</Button>
			</div>
		</div>
	{/if}

	{#if showPredicted}
		<div>
			<div class="label mb-1.5">The machine's guess</div>
			<button
				type="button"
				onclick={() => pick(predictedPart!.part_num)}
				disabled={saving}
				class="flex w-full items-center gap-2 rounded-item bg-info-soft px-3 py-2 hover:bg-hover disabled:opacity-45"
			>
				{@render partRow(
					{
						part_num: predictedPart!.part_num,
						name: predictedPart!.name,
						part_img_url: predictedPart!.part_img_url,
						category: predictedPart!.category_name
					},
					'predicted'
				)}
				<span class="shrink-0 text-sm font-medium text-info-ink">Confirm</span>
			</button>
		</div>
	{:else if !predictedPart && !selectedPart && !cantTell}
		<Alert tone="warning">The machine couldn't identify this piece. Search below for what it is.</Alert>
	{/if}

	<div class="flex flex-col gap-1.5">
		<div class="label">Search every part</div>
		<Input type="search" bind:value={query} oninput={scheduleSearch} placeholder="A name or number: plate 1 x 3, 3623" />
		<Select
			size="sm"
			label="Category"
			value={String(catId)}
			options={[{ value: '', label: 'All categories' }, ...categories.map((cat) => ({ value: String(cat.id), label: cat.name }))]}
			onchange={(v: string) => {
				catId = v === '' ? '' : Number(v);
				void runSearch();
			}}
		/>
	</div>

	{#if searching}
		<div class="flex justify-center py-3"><Spinner size={24} /></div>
	{:else if searched && results.length === 0}
		<p class="py-3 text-center text-sm text-ink-muted">No parts match.</p>
	{:else if results.length > 0}
		<ul class="flex max-h-80 flex-col gap-0.5 overflow-y-auto">
			{#each results as part (part.part_num)}
				{@const chosen = part.part_num === selectedNum}
				<li>
					<button
						type="button"
						onclick={() => pick(part.part_num)}
						disabled={saving}
						class="flex w-full items-center gap-2 rounded-item px-3 py-2 disabled:opacity-45 {chosen ? 'bg-primary-soft' : 'hover:bg-hover'}"
					>
						{@render partRow(
							{ part_num: part.part_num, name: part.name, part_img_url: part.part_img_url, category: part._category_name },
							chosen ? 'selected' : 'result'
						)}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>
