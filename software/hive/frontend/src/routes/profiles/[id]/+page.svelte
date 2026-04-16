<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type SortingProfileDetail, type SortingProfileSetProgressResponse } from '$lib/api';
	import Modal from '$lib/components/Modal.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let loading = $state(true);
	let profile = $state<SortingProfileDetail | null>(null);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let settingsName = $state('');
	let settingsDescription = $state('');
	let settingsVisibility = $state<'private' | 'unlisted' | 'public'>('private');
	let settingsTags = $state('');
	let savingSettings = $state(false);
	let libraryBusy = $state(false);
	let forking = $state(false);
	let showDeleteModal = $state(false);
	let deletingProfile = $state(false);
	let setProgress = $state<SortingProfileSetProgressResponse | null>(null);
	let setProgressLoading = $state(false);
	let setProgressError = $state<string | null>(null);

	const profileId = $derived(page.params.id ?? '');
	const cv = $derived(profile?.current_version ?? null);
	const catCount = $derived(cv?.categories ? Object.keys(cv.categories).length : 0);
	const machineProgress = $derived(setProgress?.machines ?? []);

	const stats = $derived.by(() => {
		if (!profile || !cv) return [];
		return [
			{ label: 'Parts', value: cv.compiled_part_count },
			{ label: 'Categories', value: catCount },
			{ label: 'Coverage', value: coveragePct(cv.coverage_ratio) },
			{ label: 'Library Saves', value: profile.library_count },
			{ label: 'Forks', value: profile.fork_count },
			{ label: 'Latest Version', value: `v${profile.latest_version_number}` }
		];
	});

	const sortedCategories = $derived.by(() => {
		if (!cv) return [];
		const cats = cv.categories ?? {};
		const perCat = cv.compiled_stats && typeof cv.compiled_stats.per_category === 'object' && cv.compiled_stats.per_category !== null
			? (cv.compiled_stats.per_category as Record<string, { parts?: number }>) : {};
		const entries = Object.entries(cats).map(([id, c]) => ({
			id, name: c.name, parts: perCat[id]?.parts ?? 0, isFallback: id === cv.default_category_id
		})).sort((a, b) => b.parts - a.parts);
		const max = Math.max(...entries.map((e) => e.parts), 1);
		return entries.map((e) => ({ ...e, pct: Math.max((e.parts / max) * 100, 1) }));
	});

	const parsedTags = $derived(settingsTags.split(',').map((t) => t.trim()).filter(Boolean));

	$effect(() => { if (profileId) void loadProfile(); });

	$effect(() => {
		if (!profileId || profile?.profile_type !== 'set') {
			setProgress = null;
			setProgressError = null;
			return;
		}
		void loadSetProgress();
		const intervalId = setInterval(() => {
			void loadSetProgress();
		}, 10000);
		return () => clearInterval(intervalId);
	});

	async function loadProfile() {
		loading = true; error = null;
		try {
			const d = await api.getSortingProfile(profileId);
			profile = d; settingsName = d.name; settingsDescription = d.description ?? '';
			settingsVisibility = d.visibility; settingsTags = d.tags.join(', ');
		} catch (e: any) { error = e.error || 'Failed to load profile'; }
		finally { loading = false; }
	}

	async function loadSetProgress() {
		if (!profileId) return;
		setProgressLoading = true;
		try {
			setProgress = await api.getSortingProfileSetProgress(profileId);
			setProgressError = null;
		} catch (e: any) {
			setProgressError = e.error || 'Failed to load set progress';
		} finally {
			setProgressLoading = false;
		}
	}

	async function saveSettings() {
		if (!profile) return;
		savingSettings = true; error = null; success = null;
		try {
			const u = await api.updateSortingProfile(profile.id, {
				name: settingsName, description: settingsDescription || null,
				visibility: settingsVisibility, tags: parsedTags
			});
			profile = { ...profile, ...u, current_version: profile.current_version, versions: profile.versions };
			success = 'Settings saved.';
		} catch (e: any) { error = e.error || 'Failed to save settings'; }
		finally { savingSettings = false; }
	}

	async function toggleLibrary() {
		if (!profile) return;
		libraryBusy = true; error = null; success = null;
		try {
			if (profile.saved_in_library) {
				await api.removeSortingProfileFromLibrary(profile.id); success = 'Removed from your library.';
			} else {
				await api.saveSortingProfileToLibrary(profile.id); success = 'Saved to your library.';
			}
			await loadProfile();
		} catch (e: any) { error = e.error || 'Failed to update library'; }
		finally { libraryBusy = false; }
	}

	async function forkProfile() {
		if (!profile) return;
		forking = true; error = null;
		try {
			const fork = await api.forkSortingProfile(profile.id, { add_to_library: true, name: `${profile.name} (Fork)` });
			goto(`/profiles/${fork.id}/edit`);
		} catch (e: any) { error = e.error || 'Failed to fork profile'; }
		finally { forking = false; }
	}

	async function deleteProfile() {
		if (!profile) return;
		deletingProfile = true; error = null;
		try { await api.deleteSortingProfile(profile.id); goto('/profiles?scope=mine'); }
		catch (e: any) { error = e.error || 'Failed to delete profile'; }
		finally { deletingProfile = false; }
	}

	function timeAgo(d: string): string {
		const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000);
		if (s < 60) return 'just now';
		const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
		const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
		const days = Math.floor(h / 24); if (days < 30) return `${days}d ago`;
		return new Date(d).toLocaleDateString();
	}

	function coveragePct(v: number | null | undefined): string {
		return v == null ? 'n/a' : `${(v * 100).toFixed(1)}%`;
	}

	function percent(found: number, needed: number): number {
		if (needed <= 0) return 0;
		return Math.round((found / needed) * 100);
	}

	function removeTag(tag: string) { settingsTags = parsedTags.filter((t) => t !== tag).join(', '); }
</script>

<svelte:head><title>{profile ? `${profile.name} - Hive` : 'Sorting Profile - Hive'}</title></svelte:head>

{#if loading}
	<Spinner />
{:else if !profile}
	<div class="border border-primary/20 bg-primary-light p-4 text-sm text-primary">{error ?? 'Profile not found.'}</div>
{:else}
	<div class="space-y-6">
		<!-- Header -->
		<div>
			<a href="/profiles" class="text-sm text-primary hover:text-primary-hover">&larr; Profiles</a>
			<h1 class="mt-2 text-2xl font-bold text-text">{profile.name}</h1>
			{#if profile.description}<p class="mt-1 text-sm text-text-muted">{profile.description}</p>{/if}
			<div class="mt-3 flex flex-wrap items-center gap-2">
				{#each profile.tags as tag}
					<span class="border border-primary/20 bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">{tag}</span>
				{/each}
				{#if profile.is_owner}
					<span class="border border-border bg-bg px-2 py-0.5 text-xs font-medium text-text-muted">{profile.visibility}</span>
				{/if}
			</div>
			{#if profile.source}
				<p class="mt-2 text-sm text-text-muted">Forked from <span class="font-medium text-text">{profile.source.profile_name}</span>{#if profile.source.version_number} v{profile.source.version_number}{/if}</p>
			{/if}
			<p class="mt-1 text-xs text-text-muted">by {profile.owner.display_name ?? profile.owner.github_login ?? 'Unknown'}</p>
		</div>

		<!-- Stats Bar -->
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
			{#each stats as s}
				<div class="border border-border bg-white p-4">
					<div class="text-lg font-semibold text-text">{s.value}</div>
					<div class="flex items-center gap-2 text-xs font-medium text-info"><span class="inline-block h-2.5 w-2.5 bg-info"></span>{s.label}</div>
				</div>
			{/each}
		</div>

		{#if error}<div class="border border-primary/20 bg-primary-light p-3 text-sm text-primary">{error}</div>{/if}
		{#if success}<div class="border border-success/20 bg-[#F0F9F5] p-3 text-sm text-success">{success}</div>{/if}

		<!-- Action Buttons -->
		<div class="flex flex-wrap gap-2">
			{#if profile.is_owner}
				<a href={`/profiles/${profile.id}/edit`} class="inline-block bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Edit Profile</a>
			{:else}
				<button onclick={() => void toggleLibrary()} disabled={libraryBusy} class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg disabled:opacity-50">
					{libraryBusy ? 'Updating...' : profile.saved_in_library ? 'In Library \u2713' : 'Save to Library'}
				</button>
				<button onclick={() => void forkProfile()} disabled={forking} class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg disabled:opacity-50">
					{forking ? 'Forking...' : 'Fork this Profile'}
				</button>
			{/if}
			{#if profile.is_owner && profile.saved_in_library}
				<button onclick={() => void toggleLibrary()} disabled={libraryBusy} class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg disabled:opacity-50">
					{libraryBusy ? 'Updating...' : 'In Library \u2713'}
				</button>
			{/if}
		</div>

		<!-- Categories Overview -->
		{#if sortedCategories.length > 0}
			<div class="border border-border bg-white p-6">
				<h2 class="mb-4 text-lg font-semibold text-text">Categories</h2>
				<div class="space-y-2">
					{#each sortedCategories as cat}
						<div class="flex items-center gap-3">
							<div class="w-40 truncate text-sm text-text">{cat.name}{#if cat.isFallback} <span class="text-xs text-text-muted">(fallback)</span>{/if}</div>
							<div class="flex-1"><div class="h-5 bg-primary-light" style="width: {cat.pct}%"><div class="h-full bg-info" style="width: 100%"></div></div></div>
							<div class="w-20 text-right text-sm text-text-muted">{cat.parts} parts</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		{#if profile.profile_type === 'set'}
			<div class="border border-border bg-white p-6">
				<div class="flex flex-wrap items-center justify-between gap-3">
					<div>
						<h2 class="text-lg font-semibold text-text">Machine Progress</h2>
						<p class="mt-1 text-sm text-text-muted">
							Progress synced back from your assigned machines for this set-based profile.
						</p>
					</div>
					<a href="/machines" class="text-sm font-medium text-primary hover:text-primary-hover">Manage Machines</a>
				</div>

				{#if setProgressError}
					<div class="mt-4 border border-primary/20 bg-primary-light p-3 text-sm text-primary">{setProgressError}</div>
				{:else if setProgressLoading && !setProgress}
					<div class="mt-4 text-sm text-text-muted">Loading progress...</div>
				{:else if machineProgress.length === 0}
					<div class="mt-4 border border-dashed border-border p-4 text-sm text-text-muted">
						No machines you own are currently reporting progress for this profile.
					</div>
				{:else}
					<div class="mt-5 space-y-4">
						{#each machineProgress as machine}
							<div class="border border-border p-4">
								<div class="flex flex-wrap items-start justify-between gap-3">
									<div>
										<div class="text-sm font-semibold text-text">{machine.machine_name}</div>
										<div class="mt-1 text-xs text-text-muted">
											Desired v{machine.desired_version_number ?? 'n/a'}
											{#if machine.active_version_number}
												· Active v{machine.active_version_number}
											{:else}
												· Waiting for activation
											{/if}
										</div>
										{#if machine.updated_at}
											<div class="mt-1 text-xs text-text-muted">
												Last progress update {timeAgo(machine.updated_at)}
											</div>
										{/if}
									</div>
									<div class="min-w-[9rem] text-right">
										<div class="text-lg font-semibold text-text">
											{machine.overall_found}/{machine.overall_needed}
										</div>
										<div class="text-xs text-text-muted">{machine.overall_pct}% complete</div>
									</div>
								</div>

								<div class="mt-3 h-2 w-full bg-bg">
									<div
										class="h-full bg-success transition-all"
										style="width: {Math.min(machine.overall_pct, 100)}%"
									></div>
								</div>

								{#if machine.sets.length > 0}
									<div class="mt-4 space-y-2">
										{#each machine.sets as set}
											<div class="border border-border bg-bg p-3">
												<div class="flex items-center justify-between gap-3">
													<div class="min-w-0">
														<div class="truncate text-sm font-medium text-text">{set.name}</div>
														{#if set.name !== set.set_num}
															<div class="truncate text-xs text-text-muted">{set.set_num}</div>
														{/if}
													</div>
													<div class="text-right text-xs text-text-muted">
														{set.total_found}/{set.total_needed} ({set.pct}%)
													</div>
												</div>
												<div class="mt-2 h-1.5 w-full bg-white">
													<div
														class="h-full bg-info transition-all"
														style="width: {Math.min(percent(set.total_found, set.total_needed), 100)}%"
													></div>
												</div>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<!-- Version History -->
		{#if profile.versions.length > 0}
			<div class="border border-border bg-white p-6">
				<h2 class="mb-4 text-lg font-semibold text-text">Version History</h2>
				<div class="space-y-3">
					{#each [...profile.versions].reverse() as v}
						<div class="border border-border p-4">
							<div class="flex items-start justify-between gap-3">
								<div>
									<div class="flex flex-wrap items-center gap-2">
										<span class="text-sm font-semibold text-text">v{v.version_number}</span>
										{#if v.is_published}<span class="border border-success/20 bg-[#F0F9F5] px-2 py-0.5 text-xs font-medium text-success">Published</span>{/if}
										{#if v.label}<span class="border border-border bg-bg px-2 py-0.5 text-xs font-medium text-text-muted">{v.label}</span>{/if}
									</div>
									{#if v.change_note}<p class="mt-1 text-sm text-text-muted">{v.change_note}</p>{/if}
									<p class="mt-1 text-xs text-text-muted">{timeAgo(v.created_at)}</p>
								</div>
								<div class="text-right text-xs text-text-muted">
									<div>{v.compiled_part_count} parts</div>
									<div>{coveragePct(v.coverage_ratio)} coverage</div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Settings (Owner only) -->
		{#if profile.is_owner}
			<div class="border border-border bg-white p-6">
				<h2 class="mb-4 text-lg font-semibold text-text">Settings</h2>
				<div class="space-y-4">
					<div>
						<label for="s-name" class="mb-1 block text-sm font-medium text-text">Name</label>
						<input id="s-name" type="text" bind:value={settingsName} class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
					</div>
					<div>
						<label for="s-desc" class="mb-1 block text-sm font-medium text-text">Description</label>
						<textarea id="s-desc" rows="3" bind:value={settingsDescription} class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"></textarea>
					</div>
					<div>
						<label for="s-vis" class="mb-1 block text-sm font-medium text-text">Visibility</label>
						<select id="s-vis" bind:value={settingsVisibility} class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
							<option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option>
						</select>
					</div>
					<div>
						<label for="s-tags" class="mb-1 block text-sm font-medium text-text">Tags</label>
						<input id="s-tags" type="text" bind:value={settingsTags} placeholder="starter, workshop, plates" class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
						{#if parsedTags.length > 0}
							<div class="mt-2 flex flex-wrap gap-1">
								{#each parsedTags as tag}
									<span class="inline-flex items-center gap-1 border border-primary/20 bg-primary-light px-2 py-0.5 text-xs font-medium text-primary">
										{tag}<button onclick={() => removeTag(tag)} class="text-primary/60 hover:text-primary" aria-label="Remove tag {tag}">&times;</button>
									</span>
								{/each}
							</div>
						{/if}
					</div>
					<button onclick={() => void saveSettings()} disabled={savingSettings} class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
						{savingSettings ? 'Saving...' : 'Save Changes'}
					</button>
				</div>
				<div class="mt-6 border-t border-border pt-6">
					<h3 class="mb-3 text-sm font-semibold text-primary">Danger Zone</h3>
					<button onclick={() => { showDeleteModal = true; }} class="border border-primary/30 px-4 py-2 text-sm font-medium text-primary hover:bg-primary-light">Delete this Profile</button>
				</div>
			</div>
		{/if}
	</div>
{/if}

<Modal open={showDeleteModal} title="Delete Sorting Profile" onclose={() => { showDeleteModal = false; }}>
	<div class="space-y-4">
		<p class="text-sm text-text-muted">This removes the profile, all versions, AI messages, and machine assignments that point at it. This cannot be undone.</p>
		<div class="flex justify-end gap-2">
			<button onclick={() => { showDeleteModal = false; }} class="border border-border bg-white px-4 py-2 text-sm font-medium text-text hover:bg-bg">Cancel</button>
			<button onclick={() => void deleteProfile()} disabled={deletingProfile} class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{deletingProfile ? 'Deleting...' : 'Delete Profile'}</button>
		</div>
	</div>
</Modal>
