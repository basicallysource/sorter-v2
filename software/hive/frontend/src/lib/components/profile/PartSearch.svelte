<script lang="ts">
	import { api, type ProfileCatalogSearchResult } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import X from '@lucide/svelte/icons/x';

	let {
		onSelect,
		onCancel,
		title = 'Add a LEGO part',
		autofocus = false
	}: {
		onSelect: (part: ProfileCatalogSearchResult) => void;
		onCancel?: () => void;
		title?: string;
		// Put the cursor in the search box when it appears.
		autofocus?: boolean;
	} = $props();

	let field = $state<HTMLInputElement>();
	$effect(() => {
		if (autofocus) field?.focus();
	});

	let query = $state('');
	let results = $state<ProfileCatalogSearchResult[]>([]);
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
		debounceTimer = setTimeout(() => void doSearch(q), 300);
	}

	// The part's BrickLink ID: what a sorter reports a piece by.
	function bricklinkId(part: ProfileCatalogSearchResult): string | null {
		const ids = part.external_ids?.BrickLink;
		return Array.isArray(ids) && ids.length > 0 ? String(ids[0]) : null;
	}

	async function doSearch(q: string) {
		loading = true;
		searched = true;
		try {
			const res = await api.searchProfileCatalogParts({ q, limit: 20 });
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
	<Input
		type="search"
		bind:value={query}
		bind:element={field}
		oninput={handleInput}
		placeholder="Search parts, like technic pin, 2780 or axle"
	/>

	{#if loading}
		<p class="flex items-center justify-center gap-2 py-4 text-sm text-ink-muted"><Spinner size={14} />Searching</p>
	{:else if searched && results.length === 0}
		<p class="py-4 text-center text-sm text-ink-muted">No parts found.</p>
	{:else if results.length > 0}
		<ul class="max-h-72 divide-y divide-line overflow-y-auto">
			{#each results as part (part.part_num)}
				<li>
					<PartTile
						name={part.name}
						imgUrl={part.part_img_url}
						bricklinkId={bricklinkId(part)}
						partNum={part.part_num}
						padded={false}
						class="py-2"
						onclick={() => onSelect(part)}
					/>
				</li>
			{/each}
		</ul>
	{/if}
</div>
