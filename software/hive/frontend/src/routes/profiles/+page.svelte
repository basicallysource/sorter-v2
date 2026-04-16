<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type SortingProfileSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	let profiles = $state<SortingProfileSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let busyProfileId = $state<string | null>(null);
	let creating = $state(false);
	let deleteTarget = $state<SortingProfileSummary | null>(null);
	let deleting = $state(false);

	async function createProfile() {
		creating = true;
		error = null;
		try {
			const profile = await api.createSortingProfile({ name: 'Untitled Profile', visibility: 'private' });
			goto(`/profiles/${profile.id}/edit?new=1`);
		} catch (e: any) {
			error = e.error || 'Failed to create profile';
			creating = false;
		}
	}

	const scope = 'mine' as const;

	$effect(() => {
		loadProfiles();
	});

	async function loadProfiles() {
		loading = true;
		error = null;
		try {
			profiles = await api.getProfiles({ scope });
		} catch (e: any) {
			error = e.error || 'Failed to load sorting profiles';
		} finally {
			loading = false;
		}
	}

	async function confirmDelete() {
		if (!deleteTarget) return;
		deleting = true;
		error = null;
		try {
			await api.deleteSortingProfile(deleteTarget.id);
			profiles = profiles.filter(p => p.id !== deleteTarget!.id);
			deleteTarget = null;
		} catch (e: any) {
			error = e.error || 'Failed to delete profile';
		} finally {
			deleting = false;
		}
	}
</script>

<svelte:head>
	<title>Profiles - Hive</title>
</svelte:head>

<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
	<div>
		<h1 class="text-2xl font-bold text-text">Sorting Profiles</h1>
		<p class="mt-1 text-sm text-text-muted">
			Build, share, fork, and assign sorting logic across your machines.
		</p>
	</div>
	<button
		onclick={createProfile}
		disabled={creating}
		class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
	>
		{creating ? 'Creating...' : 'New Profile'}
	</button>
</div>


{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

{#if loading}
	<Spinner />
{:else if profiles.length === 0}
	<div class="border border-border bg-white p-6 text-sm text-text-muted">You have not created any profiles yet.</div>
{:else}
	<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
		{#each profiles as profile (profile.id)}
			{@const rules = profile.latest_version?.rules_summary ?? []}
			{@const activeRules = rules.filter(r => !r.disabled)}
			<a href={profile.is_owner ? `/profiles/${profile.id}/edit` : `/profiles/${profile.id}`}
				class="group flex flex-col border border-border bg-white transition-colors hover:border-text-muted">
				<!-- Header -->
				<div class="px-4 pt-4 pb-3">
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<h2 class="flex items-center gap-2 truncate text-sm font-semibold {profile.visibility === 'public' ? 'text-info' : 'text-text'}">
								{#if profile.visibility === 'public'}
									<span class="inline-block h-2.5 w-2.5 shrink-0 bg-info"></span>
								{:else}
									<span class="inline-block h-2.5 w-2.5 shrink-0 bg-text-muted"></span>
								{/if}
								{profile.name}
							</h2>
							{#if profile.description}
								<p class="mt-0.5 truncate text-xs text-text-muted">{profile.description}</p>
							{/if}
						</div>
						<div class="flex shrink-0 items-center gap-1.5">
							{#if profile.source}
								<span class="border border-warning/30 bg-warning/[0.1] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#A16207]">Fork</span>
							{/if}
							<span class="border border-border bg-bg px-1.5 py-0.5 text-[10px] font-medium text-text-muted">v{profile.latest_version_number}</span>
						</div>
					</div>
				</div>

				<!-- Rules list -->
				{#if activeRules.length > 0}
					<div class="border-t border-border px-4 py-2.5">
						<div class="space-y-1.5">
							{#each activeRules.slice(0, 6) as rule}
								<div class="flex items-center gap-2 text-xs">
									{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
										<img src={rule.set_meta.img_url} alt="" class="h-5 w-5 shrink-0 object-contain" />
									{:else}
										<svg class="h-3.5 w-3.5 shrink-0 text-text-muted" viewBox="0 0 20 20" fill="currentColor">
											<path fill-rule="evenodd" d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.092 1.092a4 4 0 00-5.558-5.558z" clip-rule="evenodd" />
											<path d="M10.748 13.93l2.523 2.523a9.987 9.987 0 01-3.27.547c-4.258 0-7.894-2.66-9.337-6.41a1.651 1.651 0 010-1.186A10.007 10.007 0 012.839 6.02L6.07 9.252a4 4 0 004.678 4.678z" />
										</svg>
									{/if}
									<span class="truncate text-text">{rule.name}</span>
									{#if rule.rule_type === 'set' && rule.set_num}
										<span class="shrink-0 font-mono text-[10px] text-text-muted">{rule.set_num}</span>
									{:else if rule.condition_count > 0}
										<span class="shrink-0 text-[10px] text-text-muted">{rule.condition_count} cond{rule.condition_count !== 1 ? 's' : ''}</span>
									{/if}
									{#if rule.child_count > 0}
										<span class="shrink-0 text-[10px] text-text-muted">+{rule.child_count} sub</span>
									{/if}
								</div>
							{/each}
							{#if activeRules.length > 6}
								<div class="text-[10px] text-text-muted">+{activeRules.length - 6} more rules</div>
							{/if}
						</div>
					</div>
				{:else if rules.length === 0}
					<div class="border-t border-border px-4 py-2.5">
						<span class="text-xs text-text-muted">No rules defined</span>
					</div>
				{/if}

				<!-- Footer -->
				<div class="mt-auto border-t border-border bg-bg px-4 py-2">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2 text-[10px] text-text-muted">
							<span>{profile.latest_version?.compiled_part_count ?? 0} parts</span>
							{#if profile.fork_count > 0}
								<span class="text-border">|</span>
								<span>{profile.fork_count} forks</span>
							{/if}
							{#if !profile.is_owner}
								<span class="text-border">|</span>
								<span>by {profile.owner.display_name ?? profile.owner.github_login ?? '?'}</span>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							{#if profile.tags.length > 0}
								<div class="flex gap-1">
									{#each profile.tags.slice(0, 3) as tag}
										<span class="border border-border bg-bg px-1.5 py-0.5 text-[10px] text-text-muted">{tag}</span>
									{/each}
								</div>
							{/if}
							{#if profile.is_owner}
								<button
									onclick={(e) => { e.preventDefault(); e.stopPropagation(); deleteTarget = profile; }}
									class="p-1 text-text-muted opacity-0 transition-opacity hover:text-primary group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
									title="Delete profile"
								>
									<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
										<path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
									</svg>
								</button>
							{/if}
						</div>
					</div>
				</div>
			</a>
		{/each}
	</div>
{/if}

{#if deleteTarget}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onkeydown={(e) => { if (e.key === 'Escape') deleteTarget = null; }} onclick={() => deleteTarget = null}>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="w-full max-w-md bg-white p-6"
			role="dialog"
			aria-modal="true"
			tabindex="-1"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<h3 class="text-lg font-semibold text-text">Delete Profile</h3>
			<p class="mt-2 text-sm text-text-muted">
				Are you sure you want to delete <span class="font-medium text-text">{deleteTarget.name}</span>? This action cannot be undone.
			</p>
			{#if error}
				<div class="mt-3 bg-primary/8 p-2 text-sm text-primary">{error}</div>
			{/if}
			<div class="mt-6 flex justify-end gap-3">
				<button
					onclick={() => deleteTarget = null}
					disabled={deleting}
					class="border border-border bg-white px-4 py-2 text-sm font-medium text-text-muted hover:bg-bg disabled:opacity-50"
				>Cancel</button>
				<button
					onclick={confirmDelete}
					disabled={deleting}
					class="bg-danger px-4 py-2 text-sm font-medium text-white hover:bg-[#7A1517] disabled:opacity-50"
				>{deleting ? 'Deleting...' : 'Delete'}</button>
			</div>
		</div>
	</div>
{/if}
