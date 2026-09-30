<script lang="ts">
	import { api, type ProfileCatalogSearchResult } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import X from '@lucide/svelte/icons/x';

	let {
		onSelect,
		onCancel
	}: {
		onSelect: (part: ProfileCatalogSearchResult) => void;
		onCancel?: () => void;
	} = $props();

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
		<h3 class="text-sm font-medium text-ink">Add a LEGO part</h3>
		{#if onCancel}<Button variant="ghost" size="sm" icon={X} label="Close" onclick={onCancel} />{/if}
	</div>
	<Input
		type="search"
		bind:value={query}
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
					<button
						type="button"
						onclick={() => onSelect(part)}
						class="flex w-full items-center gap-3 px-2 py-2 text-left hover:bg-hover"
					>
						{#if part.part_img_url}
							<img src={part.part_img_url} alt={part.name} class="size-12 shrink-0 object-contain" />
						{:else}
							<span class="flex size-12 shrink-0 items-center justify-center rounded-control bg-surface text-xs text-ink-muted"
								>No picture</span
							>
						{/if}
						<span class="min-w-0 flex-1">
							<span class="block truncate text-sm font-medium text-ink">{part.name}</span>
							<span class="block truncate text-sm text-ink-muted">
								<span class="font-mono">{part.part_num}</span>{#if part._category_name}, {part._category_name}{/if}
							</span>
						</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>
