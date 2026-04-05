<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { sortingProfileStore, type SortingProfileMetadata } from '$lib/stores/sortingProfile.svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	let profile = $state<SortingProfileMetadata | null>(null);
	let loading = $state(true);

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	async function loadProfile() {
		try {
			profile = await sortingProfileStore.load(baseUrl());
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	const categoryCount = $derived(profile ? Object.keys(profile.categories).length : 0);
	const ruleCount = $derived(profile ? profile.rules.filter(r => !r.disabled).length : 0);

	const syncState = $derived(profile?.sync_state);
	const isSynced = $derived(syncState?.version_number != null && !syncState?.last_error);

	onMount(() => {
		void loadProfile();
	});
</script>

<div class="border border-[#E2E0DB] bg-white">
	<div class="flex items-center justify-between border-b border-[#E2E0DB] bg-[#F7F6F3] px-3 py-2">
		<h3 class="text-xs font-semibold uppercase tracking-wide text-[#1A1A1A]">Active Profile</h3>
		<a href="/profiles" class="text-xs text-[#7A7770] hover:text-[#1A1A1A]">Manage</a>
	</div>

	{#if loading}
		<div class="px-3 py-4 text-center text-xs text-[#7A7770]">Loading...</div>
	{:else if !profile}
		<div class="px-3 py-4 text-center text-xs text-[#7A7770]">No profile loaded</div>
	{:else}
		<div class="p-3">
			<div class="flex items-start gap-2">
				<span class="mt-1 inline-block h-2.5 w-2.5 shrink-0 bg-[#D01012]"></span>
				<div class="min-w-0 flex-1">
					<div class="truncate text-sm font-semibold text-[#1A1A1A]">{profile.name}</div>
					{#if syncState?.version_number}
						<div class="mt-0.5 text-xs text-[#7A7770]">
							v{syncState.version_number}
							{#if syncState.version_label}
								&middot; {syncState.version_label}
							{/if}
						</div>
					{/if}
				</div>
			</div>

			<div class="mt-2.5 flex gap-3 text-xs text-[#7A7770]">
				<span>{categoryCount} categories</span>
				<span>{ruleCount} rules</span>
			</div>

			{#if syncState}
				<div class="mt-2 flex items-center gap-1.5 text-xs">
					{#if syncState.last_error}
						<span class="inline-block h-1.5 w-1.5 bg-[#D01012]"></span>
						<span class="text-[#D01012]">Sync error</span>
					{:else if isSynced}
						<span class="inline-block h-1.5 w-1.5 bg-[#00852B]"></span>
						<span class="text-[#00852B]">In sync</span>
					{/if}
					{#if syncState.target_name}
						<span class="text-[#7A7770]">&middot; {syncState.target_name}</span>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>
