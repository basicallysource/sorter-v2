<script lang="ts">
	import { page } from '$app/state';
	import { api, type SortingProfileDetail } from '$lib/api';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	type SetResult = {
		set_num: string;
		name: string;
		year: number;
		num_parts: number;
		set_img_url: string | null;
	};

	const profileId = $derived(page.params.id ?? '');
	let profile = $state<SortingProfileDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let saving = $state(false);

	let setQuery = $state('');
	let searchResults = $state<SetResult[]>([]);
	let searching = $state(false);
	let selectedSets = $state<string[]>([]);
	let includeSpares = $state(false);
	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	async function loadProfile() {
		try {
			profile = await api.getSortingProfile(profileId);
			const version = profile.current_version;
			if (version?.set_config) {
				selectedSets = [...version.set_config.sets];
				includeSpares = version.set_config.include_spares;
			}
		} catch (e: any) {
			error = e.error || 'Failed to load profile';
		} finally {
			loading = false;
		}
	}

	function handleSearchInput() {
		if (searchTimeout) clearTimeout(searchTimeout);
		if (setQuery.trim().length < 2) {
			searchResults = [];
			return;
		}
		searching = true;
		searchTimeout = setTimeout(async () => {
			try {
				const result = await api.searchSets(setQuery.trim());
				searchResults = result.results.filter(
					(r) => !selectedSets.includes(r.set_num)
				);
			} catch {
				searchResults = [];
			} finally {
				searching = false;
			}
		}, 400);
	}

	function addSet(set: SetResult) {
		if (!selectedSets.includes(set.set_num)) {
			selectedSets = [...selectedSets, set.set_num];
			searchResults = searchResults.filter((r) => r.set_num !== set.set_num);
		}
	}

	function removeSet(set_num: string) {
		selectedSets = selectedSets.filter((s) => s !== set_num);
	}

	async function handleSave() {
		if (!profile || selectedSets.length === 0) return;
		saving = true;
		error = null;
		try {
			await api.saveSortingProfileVersion(profileId, {
				name: profile.name,
				description: profile.description,
				default_category_id: 'misc',
				rules: [],
				fallback_mode: { rebrickable_categories: false, bricklink_categories: false, by_color: false },
				change_note: 'Updated set configuration',
				publish: true,
				set_config: { sets: selectedSets, include_spares: includeSpares },
			});
			goto(`/profiles/${profileId}`);
		} catch (e: any) {
			error = e.error || 'Failed to save';
		} finally {
			saving = false;
		}
	}

	onMount(loadProfile);
</script>

<svelte:head>
	<title>Manage Sets - SortHive</title>
</svelte:head>

<div class="mx-auto max-w-lg py-12">
	<a href="/profiles/{profileId}" class="mb-6 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
		<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
			<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
		</svg>
		Back to Profile
	</a>

	<h1 class="mb-2 text-2xl font-bold text-gray-900">Manage Sets</h1>

	{#if loading}
		<div class="py-12 text-center text-gray-500">Loading...</div>
	{:else if error}
		<div class="mb-4 border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{:else}
		<div class="space-y-5">
			<!-- Search -->
			<div>
				<label for="set-search" class="mb-1 block text-sm font-medium text-gray-700">Add Sets</label>
				<input
					id="set-search"
					type="text"
					bind:value={setQuery}
					oninput={handleSearchInput}
					placeholder="Search by name or set number..."
					class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
				/>

				{#if searching}
					<div class="mt-1 text-xs text-gray-400">Searching...</div>
				{/if}

				{#if searchResults.length > 0}
					<div class="mt-1 max-h-48 overflow-y-auto border border-gray-200 bg-white">
						{#each searchResults as result}
							<button
								type="button"
								class="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50"
								onclick={() => addSet(result)}
							>
								{#if result.set_img_url}
									<img src={result.set_img_url} alt="" class="h-8 w-8 object-contain" />
								{/if}
								<div class="min-w-0 flex-1">
									<div class="truncate font-medium">{result.name}</div>
									<div class="text-xs text-gray-500">{result.set_num} &middot; {result.year} &middot; {result.num_parts} parts</div>
								</div>
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Current Sets -->
			<div>
				<label class="mb-1 block text-sm font-medium text-gray-700">
					Sets in Profile ({selectedSets.length})
				</label>
				{#if selectedSets.length === 0}
					<div class="border border-dashed border-gray-300 p-4 text-center text-sm text-gray-400">
						No sets added yet. Search above to add sets.
					</div>
				{:else}
					<div class="space-y-1">
						{#each selectedSets as set_num}
							<div class="flex items-center justify-between border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
								<span class="font-medium">{set_num}</span>
								<button
									type="button"
									class="text-xs text-red-500 hover:text-red-700"
									onclick={() => removeSet(set_num)}
								>
									Remove
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<div class="flex items-center gap-2">
				<input id="include-spares" type="checkbox" bind:checked={includeSpares} class="h-4 w-4" />
				<label for="include-spares" class="text-sm text-gray-600">Include spare parts</label>
			</div>

			<button
				onclick={handleSave}
				disabled={saving || selectedSets.length === 0}
				class="w-full bg-[#D01012] px-4 py-3 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50"
			>
				{saving ? 'Compiling...' : 'Save & Compile'}
			</button>
		</div>
	{/if}
</div>
