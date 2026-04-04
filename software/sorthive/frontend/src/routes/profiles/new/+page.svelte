<script lang="ts">
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';

	type SetResult = {
		set_num: string;
		name: string;
		year: number;
		num_parts: number;
		set_img_url: string | null;
	};

	let name = $state('');
	let binCount = $state<number | undefined>(undefined);
	let profileType = $state<'rule' | 'set'>('rule');
	let creating = $state(false);
	let error = $state<string | null>(null);

	// Set search state
	let setQuery = $state('');
	let searchResults = $state<SetResult[]>([]);
	let searching = $state(false);
	let selectedSets = $state<SetResult[]>([]);
	let includeSpares = $state(false);
	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	const hasOpenRouter = $derived(Boolean(auth.user?.openrouter_configured));

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
					(r) => !selectedSets.some((s) => s.set_num === r.set_num)
				);
			} catch {
				searchResults = [];
			} finally {
				searching = false;
			}
		}, 400);
	}

	function addSet(set: SetResult) {
		if (!selectedSets.some((s) => s.set_num === set.set_num)) {
			selectedSets = [...selectedSets, set];
			searchResults = searchResults.filter((r) => r.set_num !== set.set_num);
		}
	}

	function removeSet(set_num: string) {
		selectedSets = selectedSets.filter((s) => s.set_num !== set_num);
	}

	async function handleCreate(e: Event) {
		e.preventDefault();
		if (!name.trim()) return;
		if (profileType === 'set' && selectedSets.length === 0) {
			error = 'Please add at least one set';
			return;
		}

		creating = true;
		error = null;
		try {
			const profile = await api.createSortingProfile({
				name: name.trim(),
				visibility: 'private',
				profile_type: profileType,
			});

			if (profileType === 'set') {
				// Create a version with the set config
				await api.saveSortingProfileVersion(profile.id, {
					name: profile.name,
					description: profile.description,
					default_category_id: 'misc',
					rules: [],
					fallback_mode: { rebrickable_categories: false, bricklink_categories: false, by_color: false },
					change_note: 'Initial set configuration',
					publish: true,
					set_config: {
						sets: selectedSets.map((s) => s.set_num),
						include_spares: includeSpares,
					},
				});
				goto(`/profiles/${profile.id}`);
			} else {
				const params = new URLSearchParams();
				if (binCount && binCount > 0) params.set('bins', String(binCount));
				params.set('new', '1');
				goto(`/profiles/${profile.id}/edit?${params.toString()}`);
			}
		} catch (e: any) {
			error = e.error || 'Failed to create profile';
		} finally {
			creating = false;
		}
	}
</script>

<svelte:head>
	<title>New Profile - SortHive</title>
</svelte:head>

<div class="mx-auto max-w-lg py-12">
	<a href="/profiles" class="mb-6 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
		<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
			<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
		</svg>
		Profiles
	</a>

	<h1 class="mb-2 text-2xl font-bold text-gray-900">Create a Sorting Profile</h1>
	<p class="mb-8 text-sm text-gray-500">
		Choose your profile type and configure it.
	</p>

	{#if error}
		<div class="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{/if}

	<form onsubmit={handleCreate} class="space-y-5">
		<!-- Profile Type Toggle -->
		<div>
			<label class="mb-2 block text-sm font-medium text-gray-700">Profile Type</label>
			<div class="flex gap-2">
				<button
					type="button"
					class="flex-1 border px-4 py-3 text-sm font-medium transition-colors {profileType === 'rule'
						? 'border-blue-500 bg-blue-50 text-blue-700'
						: 'border-gray-300 text-gray-600 hover:bg-gray-50'}"
					onclick={() => (profileType = 'rule')}
				>
					<div class="font-medium">Rule-based</div>
					<div class="mt-0.5 text-xs opacity-70">Sort by part properties (category, color, price)</div>
				</button>
				<button
					type="button"
					class="flex-1 border px-4 py-3 text-sm font-medium transition-colors {profileType === 'set'
						? 'border-blue-500 bg-blue-50 text-blue-700'
						: 'border-gray-300 text-gray-600 hover:bg-gray-50'}"
					onclick={() => (profileType = 'set')}
				>
					<div class="font-medium">Set-based</div>
					<div class="mt-0.5 text-xs opacity-70">Reassemble specific LEGO sets from mixed parts</div>
				</button>
			</div>
		</div>

		<div>
			<label for="profile-name" class="mb-1 block text-sm font-medium text-gray-700">
				Profile Name
			</label>
			<input
				id="profile-name"
				type="text"
				bind:value={name}
				required
				placeholder={profileType === 'set' ? 'e.g. UCS Collection Sort' : 'e.g. My Technic Sorter'}
				class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
			/>
		</div>

		{#if profileType === 'rule'}
			{#if !hasOpenRouter}
				<div class="border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
					<strong>AI Assistant requires an OpenRouter API key.</strong>
					You can still create a profile and edit rules manually, or
					<a href="/settings" class="font-medium underline hover:text-amber-900">configure your API key</a> first.
				</div>
			{/if}

			<div>
				<label for="bin-count" class="mb-1 block text-sm font-medium text-gray-700">
					How many sorting bins do you have?
				</label>
				<p class="mb-1 text-xs text-gray-400">
					Optional. Helps the AI suggest the right number of categories.
				</p>
				<input
					id="bin-count"
					type="number"
					bind:value={binCount}
					min="1"
					max="100"
					placeholder="e.g. 12"
					class="w-32 border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
				/>
			</div>
		{:else}
			<!-- Set Search -->
			<div>
				<label for="set-search" class="mb-1 block text-sm font-medium text-gray-700">
					Search for LEGO Sets
				</label>
				<input
					id="set-search"
					type="text"
					bind:value={setQuery}
					oninput={handleSearchInput}
					placeholder="Search by name or set number..."
					class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
								{:else}
									<div class="flex h-8 w-8 items-center justify-center bg-gray-100 text-xs text-gray-400">?</div>
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

			<!-- Selected Sets -->
			{#if selectedSets.length > 0}
				<div>
					<label class="mb-1 block text-sm font-medium text-gray-700">
						Selected Sets ({selectedSets.length})
					</label>
					<div class="space-y-1">
						{#each selectedSets as set}
							<div class="flex items-center gap-3 border border-gray-200 bg-gray-50 px-3 py-2">
								{#if set.set_img_url}
									<img src={set.set_img_url} alt="" class="h-8 w-8 object-contain" />
								{:else}
									<div class="flex h-8 w-8 items-center justify-center bg-gray-100 text-xs text-gray-400">?</div>
								{/if}
								<div class="min-w-0 flex-1 text-sm">
									<div class="truncate font-medium">{set.name}</div>
									<div class="text-xs text-gray-500">{set.set_num} &middot; {set.num_parts} parts</div>
								</div>
								<button
									type="button"
									class="text-xs text-red-500 hover:text-red-700"
									onclick={() => removeSet(set.set_num)}
								>
									Remove
								</button>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<div class="flex items-center gap-2">
				<input
					id="include-spares"
					type="checkbox"
					bind:checked={includeSpares}
					class="h-4 w-4"
				/>
				<label for="include-spares" class="text-sm text-gray-600">Include spare parts</label>
			</div>
		{/if}

		<button
			type="submit"
			disabled={creating || !name.trim() || (profileType === 'set' && selectedSets.length === 0)}
			class="w-full bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
		>
			{#if creating}
				<span class="flex items-center justify-center gap-2">
					<svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
					</svg>
					Creating...
				</span>
			{:else if profileType === 'set'}
				Create Set Profile
			{:else}
				Create Profile & Open Editor
			{/if}
		</button>
	</form>
</div>
