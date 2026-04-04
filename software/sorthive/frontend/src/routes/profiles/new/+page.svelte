<script lang="ts">
	import { api } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';

	let name = $state('');
	let binCount = $state<number | undefined>(undefined);
	let creating = $state(false);
	let error = $state<string | null>(null);

	const hasOpenRouter = $derived(Boolean(auth.user?.openrouter_configured));

	async function handleCreate(e: Event) {
		e.preventDefault();
		if (!name.trim()) return;

		creating = true;
		error = null;
		try {
			const profile = await api.createSortingProfile({
				name: name.trim(),
				visibility: 'private'
			});
			// Pass bin count as URL param so the editor can use it for initial AI prompt
			const params = new URLSearchParams();
			if (binCount && binCount > 0) params.set('bins', String(binCount));
			params.set('new', '1');
			goto(`/profiles/${profile.id}/edit?${params.toString()}`);
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
		Give your profile a name and start building it with the AI assistant.
	</p>

	{#if error}
		<div class="mb-4 border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{/if}

	{#if !hasOpenRouter}
		<div class="mb-6 border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
			<strong>AI Assistant requires an OpenRouter API key.</strong>
			You can still create a profile and edit rules manually, or
			<a href="/settings" class="font-medium underline hover:text-amber-900">configure your API key</a> first.
		</div>
	{/if}

	<form onsubmit={handleCreate} class="space-y-5">
		<div>
			<label for="profile-name" class="mb-1 block text-sm font-medium text-gray-700">
				Profile Name
			</label>
			<input
				id="profile-name"
				type="text"
				bind:value={name}
				required
				placeholder="e.g. My Technic Sorter"
				class="w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
			/>
		</div>

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

		<button
			type="submit"
			disabled={creating || !name.trim()}
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
			{:else}
				Create Profile & Open Editor
			{/if}
		</button>
	</form>
</div>
