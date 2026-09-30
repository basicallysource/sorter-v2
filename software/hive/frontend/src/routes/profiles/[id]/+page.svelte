<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type SortingProfileDetail, type SortingProfileSetProgressResponse } from '$lib/api';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Select from '$lib/components/Select.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import BookmarkPlus from '@lucide/svelte/icons/bookmark-plus';
	import Check from '@lucide/svelte/icons/check';
	import GitFork from '@lucide/svelte/icons/git-fork';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';

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
			{ label: 'Library saves', value: profile.library_count },
			{ label: 'Forks', value: profile.fork_count },
			{ label: 'Latest version', value: `v${profile.latest_version_number}` }
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

<svelte:head><title>{profile ? `${profile.name} - Hive` : 'Sorting profile - Hive'}</title></svelte:head>

<div>
	<Button href="/profiles" size="sm" variant="ghost" icon={ArrowLeft}>Profiles</Button>
</div>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if !profile}
	<Alert tone="danger">{error ?? 'Profile not found.'}</Alert>
{:else}
	<PageHeader title={profile.name} description={profile.description ?? undefined}>
		<div class="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
			<span>By {profile.owner.display_name ?? profile.owner.github_login ?? 'unknown'}</span>
			{#if profile.source}
				<span
					>Forked from <span class="text-ink">{profile.source.profile_name}</span>{#if profile.source.version_number}
						v{profile.source.version_number}{/if}</span
				>
			{/if}
			{#if profile.is_owner}<Badge>{sentence(profile.visibility)}</Badge>{/if}
			{#each profile.tags as tag (tag)}<Badge>{tag}</Badge>{/each}
		</div>
		{#snippet actions()}
			{#if profile!.is_owner}
				{#if profile!.saved_in_library}
					<Button icon={Check} loading={libraryBusy} onclick={() => void toggleLibrary()}>In library</Button>
				{/if}
				<Button href={`/profiles/${profile!.id}/edit`} variant="primary" icon={Pencil}>Edit profile</Button>
			{:else}
				<Button
					icon={profile!.saved_in_library ? Check : BookmarkPlus}
					loading={libraryBusy}
					onclick={() => void toggleLibrary()}>{profile!.saved_in_library ? 'In library' : 'Save to library'}</Button
				>
				<Button variant="primary" icon={GitFork} loading={forking} onclick={() => void forkProfile()}
					>Fork this profile</Button
				>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="flex flex-col gap-(--gap-panels)">
		<section aria-label="Numbers" class="overflow-hidden rounded-panel bg-surface">
			<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
				{#each stats as s (s.label)}
					<div class="border-t border-l border-line"><Stat label={s.label} value={s.value} /></div>
				{/each}
			</div>
		</section>

		{#if error}<Alert tone="danger">{error}</Alert>{/if}
		{#if success}<Alert tone="success">{success}</Alert>{/if}

		{#if sortedCategories.length > 0}
			<Panel title="Categories" description="How many parts each category holds.">
				<ul class="flex flex-col gap-2">
					{#each sortedCategories as cat (cat.id)}
						<li class="flex items-center gap-3 text-sm">
							<span class="flex w-28 min-w-0 items-center gap-2 sm:w-48">
								<span class="truncate text-ink">{cat.name}</span>
								{#if cat.isFallback}<Badge>Fallback</Badge>{/if}
							</span>
							<span class="h-3 flex-1 overflow-hidden rounded-badge bg-track">
								<span class="block h-full bg-primary" style="width: {cat.pct}%"></span>
							</span>
							<span class="num w-20 shrink-0 text-right text-ink-muted">{cat.parts} parts</span>
						</li>
					{/each}
				</ul>
			</Panel>
		{/if}

		{#if profile.profile_type === 'set'}
			<Panel
				title="Machine progress"
				description="Progress your machines sync back for this set profile."
				flush
			>
				{#snippet actions()}
					<Button href="/machines" size="sm" variant="ghost" icon={ArrowRight}>Machines</Button>
				{/snippet}
				{#if setProgressError}
					<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{setProgressError}</Alert></div>
				{:else if setProgressLoading && !setProgress}
					<div class="flex justify-center pb-(--pad-panel)"><Spinner size={24} /></div>
				{:else if machineProgress.length === 0}
					<div class="px-(--pad-panel) pb-(--pad-panel)">
						<EmptyState title="No progress yet">None of your machines is reporting progress for this profile.</EmptyState>
					</div>
				{:else}
					<ul class="divide-y divide-line">
						{#each machineProgress as machine (machine.machine_id)}
							<li class="flex flex-col gap-3 px-(--pad-panel) py-4">
								<div class="flex flex-wrap items-start justify-between gap-3">
									<div>
										<div class="font-medium text-ink">{machine.machine_name}</div>
										<div class="mt-0.5 text-sm text-ink-muted">
											Wants v{machine.desired_version_number ?? '-'}, {machine.active_version_number
												? `running v${machine.active_version_number}`
												: 'waiting to switch'}{#if machine.updated_at}. Updated {timeAgo(machine.updated_at)}.{/if}
										</div>
									</div>
									<div class="text-right">
										<div class="num text-lg font-medium text-ink">
											{machine.overall_found} of {machine.overall_needed}
										</div>
										<div class="num text-sm text-ink-muted">{machine.overall_pct}% done</div>
									</div>
								</div>
								<ProgressBar
									label={`${machine.machine_name} progress`}
									value={Math.min(machine.overall_pct, 100)}
									tone="success"
								/>
								{#if machine.sets.length > 0}
									<ul class="flex flex-col gap-3 pl-4">
										{#each machine.sets as set (set.set_num)}
											<li class="flex flex-col gap-1.5">
												<div class="flex items-baseline justify-between gap-3 text-sm">
													<span class="min-w-0 truncate text-ink"
														>{set.name}{#if set.name !== set.set_num}{' '}<span class="font-mono text-ink-muted">{set.set_num}</span>{/if}</span
													>
													<span class="num shrink-0 text-ink-muted"
														>{set.total_found} of {set.total_needed} ({set.pct}%)</span
													>
												</div>
												<ProgressBar
													label={`${set.name} progress`}
													value={Math.min(percent(set.total_found, set.total_needed), 100)}
												/>
											</li>
										{/each}
									</ul>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</Panel>
		{/if}

		{#if profile.versions.length > 0}
			<Panel title="Version history" flush>
				<ul class="divide-y divide-line">
					{#each [...profile.versions].reverse() as v (v.id)}
						<li class="flex items-start justify-between gap-3 px-(--pad-panel) py-3">
							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-2">
									<span class="num font-medium text-ink">v{v.version_number}</span>
									{#if v.is_published}<Badge tone="success">Published</Badge>{/if}
									{#if v.label}<Badge>{v.label}</Badge>{/if}
									<span class="text-sm text-ink-muted">{timeAgo(v.created_at)}</span>
								</div>
								{#if v.change_note}<p class="mt-1 text-sm text-ink-muted">{v.change_note}</p>{/if}
							</div>
							<div class="num shrink-0 text-right text-sm text-ink-muted">
								<div>{v.compiled_part_count} parts</div>
								<div>{coveragePct(v.coverage_ratio)} coverage</div>
							</div>
						</li>
					{/each}
				</ul>
			</Panel>
		{/if}

		{#if profile.is_owner}
			<Panel title="Settings">
				<div class="flex flex-col gap-4">
					<Field label="Name" for="s-name">
						<Input id="s-name" bind:value={settingsName} />
					</Field>
					<Field label="Description" for="s-desc">
						<Textarea id="s-desc" rows={3} bind:value={settingsDescription} />
					</Field>
					<Field label="Visibility" for="s-vis">
						<Select
							id="s-vis"
							bind:value={settingsVisibility}
							options={[
								{ value: 'private', label: 'Private' },
								{ value: 'unlisted', label: 'Unlisted' },
								{ value: 'public', label: 'Public' }
							]}
						/>
					</Field>
					<Field label="Tags" for="s-tags" help="Separate tags with commas.">
						<Input id="s-tags" bind:value={settingsTags} placeholder="starter, workshop, plates" />
					</Field>
					{#if parsedTags.length > 0}
						<div class="-mt-2 flex flex-wrap items-center gap-1">
							{#each parsedTags as tag (tag)}
								<span class="inline-flex items-center">
									<Badge>{tag}</Badge>
									<Button variant="ghost" size="sm" icon={X} label={`Remove the tag ${tag}`} onclick={() => removeTag(tag)} />
								</span>
							{/each}
						</div>
					{/if}
				</div>
				{#snippet footer()}
					<Button variant="primary" loading={savingSettings} onclick={() => void saveSettings()}>Save changes</Button>
				{/snippet}
			</Panel>

			<Panel title="Delete this profile">
				{#snippet actions()}
					<Button icon={Trash2} onclick={() => (showDeleteModal = true)}>Delete profile</Button>
				{/snippet}
				<p class="text-sm text-ink-muted">
					Removes every version, the assistant's messages and the machine assignments that point at it.
				</p>
			</Panel>
		{/if}
	</div>
{/if}

<Modal bind:open={showDeleteModal} title="Delete sorting profile" size="sm">
	<p class="text-sm text-ink-muted">
		This removes the profile, every version, the assistant's messages and the machine assignments that point
		at it. It cannot be undone.
	</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (showDeleteModal = false)}>Cancel</Button>
		<Button variant="danger" loading={deletingProfile} onclick={() => void deleteProfile()}>Delete profile</Button>
	{/snippet}
</Modal>
