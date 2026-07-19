<script lang="ts">
	// Pick the true mold for a piece: confirm what the machine guessed, search the
	// catalog for the right one, or say it can't be told. Mirrors the True color
	// picker next to it — the machine's guess is pinned at the top as the thing to
	// accept or replace, and every choice commits immediately.
	import { api, type PartSummary, type ProfileCatalogCategory, type ProfileCatalogSearchResult } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Ban from 'lucide-svelte/icons/ban';
	import Check from 'lucide-svelte/icons/check';
	import Search from 'lucide-svelte/icons/search';

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
			<img src={part.part_img_url} alt="" class="h-10 w-10 shrink-0 object-contain" />
		{:else}
			<div class="flex h-10 w-10 shrink-0 items-center justify-center bg-bg text-[10px] text-text-muted">
				N/A
			</div>
		{/if}
		<div class="min-w-0 flex-1">
			<div class="truncate text-sm text-text">{part.name ?? part.part_num}</div>
			<div class="truncate text-xs text-text-muted">
				{part.part_num}{part.category ? ` · ${part.category}` : ''}
			</div>
		</div>
		{#if kind === 'selected'}
			<Check class="h-4 w-4 shrink-0 text-success" />
		{/if}
	</div>
{/snippet}

<div class="space-y-2">
	<button
		onclick={onCantTell}
		disabled={saving}
		class="flex w-full items-center gap-2 border px-3 py-2 text-left text-sm disabled:opacity-50
			{cantTell ? 'border-success bg-success/10 text-text' : 'border-border text-text-muted hover:bg-bg'}"
	>
		<Ban class="h-4 w-4 shrink-0" />
		<span class="flex-1">I can't tell the part</span>
		{#if cantTell}<Check class="h-4 w-4 shrink-0 text-success" />{/if}
	</button>

	{#if selectedPart}
		<div>
			<div class="mb-1 text-xs font-semibold tracking-wide text-text-muted uppercase">Your answer</div>
			<div class="flex items-center gap-2 border border-success bg-success/10 px-3 py-2">
				{@render partRow(
					{
						part_num: selectedPart.part_num,
						name: selectedPart.name,
						part_img_url: selectedPart.part_img_url,
						category: selectedPart.category_name
					},
					'selected'
				)}
				<button
					onclick={onClear}
					disabled={saving}
					class="shrink-0 text-xs text-text-muted underline hover:text-text disabled:opacity-50"
				>
					Clear
				</button>
			</div>
		</div>
	{/if}

	{#if showPredicted}
		<div>
			<div class="mb-1 text-xs font-semibold tracking-wide text-text-muted uppercase">
				Machine's guess
			</div>
			<button
				onclick={() => pick(predictedPart!.part_num)}
				disabled={saving}
				class="flex w-full items-center gap-2 border border-info/60 bg-info/[0.06] px-3 py-2 hover:bg-info/10 disabled:opacity-50"
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
				<span class="shrink-0 text-xs text-info">Confirm</span>
			</button>
		</div>
	{:else if !predictedPart && !selectedPart && !cantTell}
		<p class="border border-warning/50 bg-warning-bg px-3 py-2 text-xs text-text-muted">
			The machine couldn't identify this piece. Search below to fill in what it is.
		</p>
	{/if}

	<div>
		<div class="mb-1 text-xs font-semibold tracking-wide text-text-muted uppercase">
			Search all parts
		</div>
		<div class="relative">
			<Search
				class="pointer-events-none absolute top-1/2 left-2 h-4 w-4 -translate-y-1/2 text-text-muted"
			/>
			<input
				type="text"
				bind:value={query}
				oninput={scheduleSearch}
				placeholder="Name or number — plate 1 x 3, 3623"
				class="w-full border border-border bg-surface py-2 pr-2 pl-8 text-sm text-text focus:border-primary focus:outline-none"
			/>
		</div>
		<select
			bind:value={catId}
			onchange={() => void runSearch()}
			class="mt-1.5 w-full border border-border bg-surface px-2 py-1.5 text-xs text-text focus:border-primary focus:outline-none"
		>
			<option value="">All categories</option>
			{#each categories as cat (cat.id)}
				<option value={cat.id}>{cat.name}</option>
			{/each}
		</select>
	</div>

	{#if searching}
		<div class="flex justify-center py-3"><Spinner /></div>
	{:else if searched && results.length === 0}
		<p class="py-3 text-center text-xs text-text-muted">No parts match.</p>
	{:else if results.length > 0}
		<div class="max-h-80 space-y-1 overflow-y-auto">
			{#each results as part (part.part_num)}
				<button
					onclick={() => pick(part.part_num)}
					disabled={saving}
					class="flex w-full items-center gap-2 border px-3 py-2 disabled:opacity-50
						{part.part_num === selectedNum
						? 'border-success bg-success/10'
						: 'border-border hover:bg-bg'}"
				>
					{@render partRow(
						{
							part_num: part.part_num,
							name: part.name,
							part_img_url: part.part_img_url,
							category: part._category_name
						},
						part.part_num === selectedNum ? 'selected' : 'result'
					)}
				</button>
			{/each}
		</div>
	{/if}
</div>
