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
		return raw === 'library' || raw === 'discover' ? raw : 'mine';
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
		class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]"
	>
		New Profile
	</a>
</div>

<div class="mb-5 flex flex-wrap items-center justify-between gap-3">
	<div class="inline-flex border border-gray-200 bg-white p-1">
		{#each (Object.keys(scopeLabels) as ProfileScope[]) as key}
			<button
				onclick={() => setScope(key)}
				class="px-3 py-1.5 text-sm font-medium {scope === key ? 'bg-[#FEF2F2] text-[#D01012]' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}"
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
			class="w-64 border border-gray-300 bg-white px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
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
	<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
		{#each profiles as profile (profile.id)}
			<a href={profile.is_owner ? `/profiles/${profile.id}/edit` : `/profiles/${profile.id}`}
				class="group border border-gray-200 bg-white p-4 transition-colors hover:border-gray-300 hover:bg-gray-50">
				<div class="mb-2 flex items-start justify-between gap-2">
					<div class="min-w-0">
						<h2 class="flex items-center gap-2 truncate text-sm font-semibold {profile.visibility === 'public' ? 'text-[#0055BF]' : 'text-gray-900'}">
							{#if profile.visibility === 'public'}
								<span class="inline-block h-2.5 w-2.5 shrink-0 bg-[#0055BF]"></span>
							{:else}
								<span class="inline-block h-2.5 w-2.5 shrink-0 bg-gray-300"></span>
							{/if}
							{profile.name}
						</h2>
						{#if profile.description}
							<p class="mt-0.5 truncate text-xs text-gray-500">{profile.description}</p>
						{/if}
					</div>
					{#if profile.source}
						<span class="shrink-0 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700">Fork</span>
					{/if}
				</div>

				<div class="flex items-center gap-3 text-xs text-gray-400">
					<span>v{profile.latest_version_number}</span>
					<span class="text-gray-200">|</span>
					<span>{profile.latest_version?.compiled_part_count ?? 0} parts</span>
					{#if profile.fork_count > 0}
						<span class="text-gray-200">|</span>
						<span>{profile.fork_count} forks</span>
					{/if}
					{#if !profile.is_owner}
						<span class="text-gray-200">|</span>
						<span>by {profile.owner.display_name ?? profile.owner.github_login ?? '?'}</span>
					{/if}
				</div>

				{#if profile.tags.length > 0}
					<div class="mt-2 flex flex-wrap gap-1">
						{#each profile.tags as tag}
							<span class="bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">{tag}</span>
						{/each}
					</div>
				{/if}

				{#if !profile.is_owner}
					<div class="mt-3 flex gap-2">
						<button
							onclick={(e) => { e.preventDefault(); e.stopPropagation(); void toggleLibrary(profile); }}
							disabled={busyProfileId === profile.id}
							class="border border-gray-300 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-50">
							{profile.saved_in_library ? 'Unsave' : 'Save'}
						</button>
						<button
							onclick={(e) => { e.preventDefault(); e.stopPropagation(); void forkProfile(profile); }}
							disabled={busyProfileId === profile.id}
							class="border border-gray-300 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-50">
							Fork
						</button>
					</div>
				{/if}
			</a>
		{/each}
	</div>
{/if}

