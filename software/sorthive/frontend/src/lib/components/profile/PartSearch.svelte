<script lang="ts">
	import { api, type ProfileCatalogSearchResult } from '$lib/api';

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

<div class="border border-[#E2E0DB] bg-white p-3">
	<div class="mb-2 flex items-center justify-between">
		<h3 class="text-sm font-semibold text-[#1A1A1A]">Add LEGO Part</h3>
		{#if onCancel}
			<button onclick={onCancel} class="p-1 text-[#7A7770] hover:text-[#1A1A1A]" aria-label="Close">
				<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
				</svg>
			</button>
		{/if}
	</div>
	<input
		type="text"
		bind:value={query}
		oninput={handleInput}
		placeholder="Search parts... (e.g. technic pin, 2780, axle)"
		class="mb-2 w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
	/>

	{#if loading}
		<div class="py-4 text-center text-xs text-[#7A7770]">Searching...</div>
	{:else if searched && results.length === 0}
		<div class="py-4 text-center text-xs text-[#7A7770]">No parts found</div>
	{:else if results.length > 0}
		<div class="max-h-72 space-y-1 overflow-y-auto">
			{#each results as part (part.part_num)}
				<button
					onclick={() => onSelect(part)}
					class="flex w-full items-center gap-3 border border-[#E2E0DB] p-2 text-left hover:bg-[#F7F6F3]"
				>
					{#if part.part_img_url}
						<img src={part.part_img_url} alt={part.name} class="h-12 w-12 shrink-0 object-contain" />
					{:else}
						<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-[#F7F6F3] text-xs text-[#7A7770]">N/A</div>
					{/if}
					<div class="min-w-0 flex-1">
						<div class="truncate text-sm font-medium text-[#1A1A1A]">{part.name}</div>
						<div class="truncate text-xs text-[#7A7770]">
							{part.part_num}
							{#if part._category_name}
								· {part._category_name}
							{/if}
						</div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
