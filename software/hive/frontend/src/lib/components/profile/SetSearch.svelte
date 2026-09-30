<script lang="ts">
	import { api } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import PartImage from '$lib/components/PartImage.svelte';
	import X from '@lucide/svelte/icons/x';

	type SetResult = {
		set_num: string;
		name: string;
		year: number;
		num_parts: number;
		img_url: string | null;
	};

	let {
		onSelect,
		onCancel,
		title = 'Add a LEGO set'
	}: { onSelect: (set: SetResult) => void; onCancel?: () => void; title?: string } = $props();

	let query = $state('');
	let minYear = $state<string | number | null>('');
	let maxYear = $state<string | number | null>('');
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
			if (minYear) opts.min_year = parseInt(String(minYear), 10);
			if (maxYear) opts.max_year = parseInt(String(maxYear), 10);
			const res = await api.searchProfileCatalogSets(q, opts);
			results = res.results;
		} catch {
			results = [];
		} finally {
			loading = false;
		}
	}
</script>

<div class="flex flex-col gap-2 rounded-control bg-well p-3">
	<div class="flex items-center justify-between">
		<h3 class="text-sm font-medium text-ink">{title}</h3>
		{#if onCancel}<Button variant="ghost" size="sm" icon={X} label="Close" onclick={onCancel} />{/if}
	</div>
	<Input type="search" bind:value={query} oninput={handleInput} placeholder="Search sets, like Space Shuttle or 10283" />
	<div class="flex items-center gap-2">
		<Input
			size="sm"
			type="number"
			class="w-28"
			bind:value={minYear}
			oninput={handleInput}
			placeholder="From year"
			min={1949}
			max={2030}
		/>
		<span class="text-sm text-ink-muted">to</span>
		<Input
			size="sm"
			type="number"
			class="w-28"
			bind:value={maxYear}
			oninput={handleInput}
			placeholder="To year"
			min={1949}
			max={2030}
		/>
	</div>

	{#if loading}
		<p class="flex items-center justify-center gap-2 py-4 text-sm text-ink-muted"><Spinner size={14} />Searching</p>
	{:else if searched && results.length === 0}
		<p class="py-4 text-center text-sm text-ink-muted">No sets found.</p>
	{:else if results.length > 0}
		<ul class="max-h-64 divide-y divide-line overflow-y-auto">
			{#each results as set (set.set_num)}
				<li>
					<button
						type="button"
						onclick={() => onSelect(set)}
						class="flex w-full items-center gap-3 px-2 py-2 text-left hover:bg-hover"
					>
						<PartImage src={set.img_url} class="size-12 shrink-0" />
						<span class="min-w-0 flex-1">
							<span class="block truncate text-sm font-medium text-ink">{set.name}</span>
							<span class="block text-sm text-ink-muted"
								><span class="font-mono">{set.set_num}</span>, {set.year}, <span class="num">{set.num_parts}</span> parts</span
							>
						</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>
