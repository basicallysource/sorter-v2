<script lang="ts">
	import { api, type SortingProfileRule } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';

	type SetResult = {
		set_num: string;
		name: string;
		year: number;
		num_parts: number;
		img_url: string | null;
	};

	let name = $state('');
	let profileType = $state<'rule' | 'set'>('rule');
	let creating = $state(false);
	let error = $state<string | null>(null);

	let selectedSets = $state<SetResult[]>([]);
	let includeSpares = $state(false);

	const hasOpenRouter = $derived(Boolean(auth.user?.openrouter_configured));

	function addSet(set: SetResult) {
		if (!selectedSets.some((s) => s.set_num === set.set_num)) {
			selectedSets = [...selectedSets, set];
		}
	}

	function removeSet(set_num: string) {
		selectedSets = selectedSets.filter((s) => s.set_num !== set_num);
	}

	function makeSetRule(set: SetResult): SortingProfileRule {
		return {
			id: crypto.randomUUID(),
			rule_type: 'set',
			name: set.name,
			match_mode: 'all',
			conditions: [],
			children: [],
			disabled: false,
			set_num: set.set_num,
			include_spares: includeSpares,
			set_meta: {
				name: set.name,
				year: set.year,
				num_parts: set.num_parts,
				img_url: set.img_url
			}
		};
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
				visibility: 'private'
			});

			if (profileType === 'set') {
				await api.saveSortingProfileVersion(profile.id, {
					name: profile.name,
					description: profile.description,
					default_category_id: 'misc',
					rules: selectedSets.map((set) => makeSetRule(set)),
					fallback_mode: { rebrickable_categories: false, bricklink_categories: false, by_color: false },
					change_note: 'Initial set rules',
					publish: true
				});
				goto(`/profiles/${profile.id}/edit`);
			} else {
				goto(`/profiles/${profile.id}/edit?new=1`);
			}
		} catch (e: any) {
			error = e.error || 'Failed to create profile';
		} finally {
			creating = false;
		}
	}
</script>

<svelte:head>
	<title>New Profile - Hive</title>
</svelte:head>

<div class="mx-auto max-w-lg py-12">
	<a href="/profiles" class="mb-6 inline-flex items-center gap-1 text-sm text-[#7A7770] hover:text-[#1A1A1A]">
		<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
			<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
		</svg>
		Profiles
	</a>

	<h1 class="mb-2 text-2xl font-bold text-[#1A1A1A]">Create a Sorting Profile</h1>
	<p class="mb-8 text-sm text-[#7A7770]">
		Choose your profile type and configure it.
	</p>

	{#if error}
		<div class="mb-4 border border-[#D01012]/20 bg-[#FEF2F2] p-3 text-sm text-[#D01012]">{error}</div>
	{/if}

	<form onsubmit={handleCreate} class="space-y-5">
		<!-- Profile Type Toggle -->
		<div>
			<div class="mb-2 text-sm font-medium text-[#1A1A1A]">Profile Type</div>
			<div class="flex gap-2">
				<button
					type="button"
					class="flex-1 border px-4 py-3 text-sm font-medium transition-colors {profileType === 'rule'
						? 'border-[#D01012] bg-[#FEF2F2] text-[#D01012]'
						: 'border-[#E2E0DB] text-[#7A7770] hover:bg-[#F7F6F3]'}"
					onclick={() => (profileType = 'rule')}
				>
					<div class="font-medium">Rule-based</div>
					<div class="mt-0.5 text-xs opacity-70">Sort by part properties (category, color, price)</div>
				</button>
				<button
					type="button"
					class="flex-1 border px-4 py-3 text-sm font-medium transition-colors {profileType === 'set'
						? 'border-[#D01012] bg-[#FEF2F2] text-[#D01012]'
						: 'border-[#E2E0DB] text-[#7A7770] hover:bg-[#F7F6F3]'}"
					onclick={() => (profileType = 'set')}
				>
					<div class="font-medium">Set-based</div>
					<div class="mt-0.5 text-xs opacity-70">Reassemble specific LEGO sets from mixed parts</div>
				</button>
			</div>
		</div>

		<div>
			<label for="profile-name" class="mb-1 block text-sm font-medium text-[#1A1A1A]">
				Profile Name
			</label>
			<input
				id="profile-name"
				type="text"
				bind:value={name}
				required
				placeholder={profileType === 'set' ? 'e.g. UCS Collection Sort' : 'e.g. My Technic Sorter'}
				class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
			/>
		</div>

		{#if profileType === 'rule'}
			{#if !hasOpenRouter}
				<div class="border border-[#FFD500]/30 bg-[#FFFBEB] p-4 text-sm text-[#A16207]">
					<strong>AI Assistant requires an OpenRouter API key.</strong>
					You can still create a profile and edit rules manually, or
					<a href="/settings" class="font-medium underline hover:text-[#A16207]">configure your API key</a> first.
				</div>
			{/if}
		{:else}
			<div>
				<div class="mb-1 text-sm font-medium text-[#1A1A1A]">
					Add LEGO Sets
				</div>
				<SetSearch onSelect={addSet} />
			</div>

			{#if selectedSets.length > 0}
				<div>
					<div class="mb-1 text-sm font-medium text-[#1A1A1A]">
						Selected Sets ({selectedSets.length})
					</div>
					<div class="space-y-1">
						{#each selectedSets as set}
							<div class="flex items-center gap-3 border border-[#E2E0DB] bg-[#F7F6F3] px-3 py-2">
								{#if set.img_url}
									<img src={set.img_url} alt="" class="h-8 w-8 object-contain" />
								{:else}
									<div class="flex h-8 w-8 items-center justify-center bg-[#F7F6F3] text-xs text-[#7A7770]">?</div>
								{/if}
								<div class="min-w-0 flex-1 text-sm">
									<div class="truncate font-medium">{set.name}</div>
									<div class="text-xs text-[#7A7770]">{set.set_num} &middot; {set.num_parts} parts</div>
								</div>
								<button
									type="button"
									class="text-xs text-[#D01012] hover:text-[#B00E10]"
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
				<label for="include-spares" class="text-sm text-[#7A7770]">Include spare parts</label>
			</div>
		{/if}

		<button
			type="submit"
			disabled={creating || !name.trim() || (profileType === 'set' && selectedSets.length === 0)}
			class="w-full bg-[#D01012] px-4 py-3 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50"
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
				Create Profile & Open Set Editor
			{:else}
				Create Profile & Open Editor
			{/if}
		</button>
	</form>
</div>
