<script lang="ts">
	import { api } from '$lib/api';

	type SetResult = {
		set_num: string;
		name: string;
		year: number;
		num_parts: number;
		img_url: string | null;
	};

	let { onSelect, onCancel }: { onSelect: (set: SetResult) => void; onCancel?: () => void } = $props();

	let query = $state('');
	let minYear = $state('');
	let maxYear = $state('');
	let results = $state<SetResult[]>([]);
	let loading = $state(false);
	let searched = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	function handleInput() {
		if (debounceTimer) clearTimeout(debounceTimer);
		const q = query.trim();
		if (!q) {
			results = [];
			searched = false;
			return;
		}
		debounceTimer = setTimeout(() => void doSearch(q), 400);
	}

	async function doSearch(q: string) {
		loading = true;
		searched = true;
		try {
			const opts: { min_year?: number; max_year?: number } = {};
			if (minYear) opts.min_year = parseInt(minYear, 10);
			if (maxYear) opts.max_year = parseInt(maxYear, 10);
			const res = await api.searchProfileCatalogSets(q, opts);
			results = res.results;
		} catch {
			results = [];
		} finally {
			loading = false;
		}
	}
</script>

<div class="border border-border bg-white p-3">
	<div class="mb-2 flex items-center justify-between">
		<h3 class="text-sm font-semibold text-text">Add LEGO Set</h3>
		{#if onCancel}
			<button onclick={onCancel} class="p-1 text-text-muted hover:text-text" aria-label="Close">
				<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
				</svg>
			</button>
		{/if}
	</div>
	<input type="text" bind:value={query} oninput={handleInput}
		placeholder="Search sets... (e.g. Space Shuttle, 10283)"
		class="mb-2 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
	<div class="mb-2 flex items-center gap-2">
		<input type="number" bind:value={minYear} oninput={handleInput}
			placeholder="From year" min="1949" max="2030"
			class="w-24 border border-border px-2 py-1 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
		<span class="text-xs text-text-muted">&ndash;</span>
		<input type="number" bind:value={maxYear} oninput={handleInput}
			placeholder="To year" min="1949" max="2030"
			class="w-24 border border-border px-2 py-1 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
	</div>

	{#if loading}
		<div class="py-4 text-center text-xs text-text-muted">Searching...</div>
	{:else if searched && results.length === 0}
		<div class="py-4 text-center text-xs text-text-muted">No sets found</div>
	{:else if results.length > 0}
		<div class="max-h-64 space-y-1 overflow-y-auto">
			{#each results as set (set.set_num)}
				<button onclick={() => onSelect(set)}
					class="flex w-full items-center gap-3 border border-border p-2 text-left hover:bg-bg">
					{#if set.img_url}
						<img src={set.img_url} alt={set.name} class="h-12 w-12 shrink-0 object-contain" />
					{:else}
						<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-bg text-xs text-text-muted">N/A</div>
					{/if}
					<div class="min-w-0 flex-1">
						<div class="truncate text-sm font-medium text-text">{set.name}</div>
						<div class="text-xs text-text-muted">{set.set_num} · {set.year} · {set.num_parts} parts</div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
