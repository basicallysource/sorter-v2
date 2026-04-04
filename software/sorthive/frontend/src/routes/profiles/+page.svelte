<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type SortingProfileSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	type ProfileScope = 'discover' | 'library' | 'mine';

	const scopeLabels: Record<ProfileScope, string> = {
		discover: 'Discover',
		library: 'My Library',
		mine: 'My Profiles'
	};

	let profiles = $state<SortingProfileSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let search = $state('');
	let busyProfileId = $state<string | null>(null);

	const scope = $derived.by(() => {
		const raw = page.url.searchParams.get('scope');
		return raw === 'library' || raw === 'mine' ? raw : 'discover';
	});

	const emptyState = $derived.by(() => {
		if (scope === 'library') return 'No profiles in your library yet.';
		if (scope === 'mine') return 'You have not created any profiles yet.';
		return 'No public profiles found yet.';
	});

	$effect(() => {
		void scope;
		loadProfiles();
	});

	async function loadProfiles() {
		loading = true;
		error = null;
		try {
			profiles = await api.getProfiles({ scope, q: search.trim() || undefined });
		} catch (e: any) {
			error = e.error || 'Failed to load sorting profiles';
		} finally {
			loading = false;
		}
	}

	function setScope(nextScope: ProfileScope) {
		const url = new URL(page.url);
		if (nextScope === 'discover') {
			url.searchParams.delete('scope');
		} else {
			url.searchParams.set('scope', nextScope);
		}
		goto(url.pathname + url.search, { keepFocus: true, noScroll: true });
	}

	async function toggleLibrary(profile: SortingProfileSummary) {
		busyProfileId = profile.id;
		error = null;
		try {
			if (profile.saved_in_library) {
				await api.removeSortingProfileFromLibrary(profile.id);
			} else {
				await api.saveSortingProfileToLibrary(profile.id);
			}
			await loadProfiles();
		} catch (e: any) {
			error = e.error || 'Failed to update library';
		} finally {
			busyProfileId = null;
		}
	}

	async function forkProfile(profile: SortingProfileSummary) {
		busyProfileId = profile.id;
		error = null;
		try {
			const fork = await api.forkSortingProfile(profile.id, { add_to_library: true });
			goto(`/profiles/${fork.id}`);
		} catch (e: any) {
			error = e.error || 'Failed to fork profile';
		} finally {
			busyProfileId = null;
		}
	}

	function latestLabel(profile: SortingProfileSummary): string {
		if (profile.latest_published_version) {
			return `Latest public: v${profile.latest_published_version.version_number}`;
		}
		if (profile.latest_version) {
			return `Latest draft: v${profile.latest_version.version_number}`;
		}
		return 'No versions yet';
	}
</script>

<svelte:head>
	<title>Profiles - SortHive</title>
</svelte:head>

<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
	<div>
		<h1 class="text-2xl font-bold text-gray-900">Sorting Profiles</h1>
		<p class="mt-1 text-sm text-gray-500">
			Build, share, fork, and assign sorting logic across your machines.
		</p>
	</div>
	<a
		href="/profiles/new"
		class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
	>
		New Profile
	</a>
</div>

<div class="mb-5 flex flex-wrap items-center justify-between gap-3">
	<div class="inline-flex border border-gray-200 bg-white p-1">
		{#each (Object.keys(scopeLabels) as ProfileScope[]) as key}
			<button
				onclick={() => setScope(key)}
				class="px-3 py-1.5 text-sm font-medium {scope === key ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
			>
				{scopeLabels[key]}
			</button>
		{/each}
	</div>
	<form
		class="flex gap-2"
		onsubmit={(e) => {
			e.preventDefault();
			void loadProfiles();
		}}
	>
		<input
			type="search"
			bind:value={search}
			placeholder="Search profiles"
			class="w-64 border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
		/>
		<button
			type="submit"
			class="border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
		>
			Search
		</button>
	</form>
</div>

{#if error}
	<div class="mb-4 bg-red-50 p-3 text-sm text-red-700">{error}</div>
{/if}

{#if loading}
	<Spinner />
{:else if profiles.length === 0}
	<div class="border border-gray-200 bg-white p-6 text-sm text-gray-500">{emptyState}</div>
{:else}
	<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
		{#each profiles as profile (profile.id)}
			<div class="border border-gray-200 bg-white p-4">
				<div class="mb-3 flex items-start justify-between gap-3">
					<div>
						<div class="mb-1 flex flex-wrap items-center gap-2">
							<h2 class="text-lg font-semibold text-gray-900">{profile.name}</h2>
							<span class="bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
								{profile.visibility}
							</span>
							{#if profile.source}
								<span class="bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
									Fork
								</span>
							{/if}
						</div>
						<p class="text-sm text-gray-500">
							by {profile.owner.display_name ?? profile.owner.github_login ?? 'Unknown'}
						</p>
					</div>
					<div class="text-right text-xs text-gray-500">
						<div>{latestLabel(profile)}</div>
						<div>{profile.library_count} saves</div>
					</div>
				</div>

				{#if profile.description}
					<p class="mb-3 text-sm text-gray-600">{profile.description}</p>
				{/if}

				{#if profile.tags.length > 0}
					<div class="mb-3 flex flex-wrap gap-1.5">
						{#each profile.tags as tag}
							<span class="bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">{tag}</span>
						{/each}
					</div>
				{/if}

				<div class="mb-4 grid grid-cols-3 gap-2 text-center text-xs">
					<div class="bg-gray-50 p-2">
						<div class="text-lg font-semibold text-gray-900">{profile.latest_version_number}</div>
						<div class="text-gray-500">Versions</div>
					</div>
					<div class="bg-gray-50 p-2">
						<div class="text-lg font-semibold text-gray-900">{profile.fork_count}</div>
						<div class="text-gray-500">Forks</div>
					</div>
					<div class="bg-gray-50 p-2">
						<div class="text-lg font-semibold text-gray-900">{profile.latest_version?.compiled_part_count ?? 0}</div>
						<div class="text-gray-500">Mapped Parts</div>
					</div>
				</div>

				<div class="flex flex-wrap gap-2">
					<a
						href={`/profiles/${profile.id}`}
						class="border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
					>
						View
					</a>
					{#if profile.is_owner}
						<a
							href={`/profiles/${profile.id}/edit`}
							class="bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
						>
							Edit
						</a>
					{:else}
						<button
							onclick={() => void toggleLibrary(profile)}
							disabled={busyProfileId === profile.id}
							class="border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
						>
							{profile.saved_in_library ? 'Remove from Library' : 'Save to Library'}
						</button>
						<button
							onclick={() => void forkProfile(profile)}
							disabled={busyProfileId === profile.id}
							class="border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
						>
							Fork
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
{/if}

