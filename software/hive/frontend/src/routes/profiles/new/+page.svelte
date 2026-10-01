<script lang="ts">
	import { api, type Kit, type SortingProfileRule } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { goto } from '$app/navigation';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import RadioGroup from '$lib/components/RadioGroup.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { uuid } from '$lib/uuid';

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

	// A kit bin for a kit: it collects the kit's parts until each line is full.
	function makeKitRule(kit: Kit): SortingProfileRule {
		return {
			id: uuid(),
			rule_type: 'kit',
			kit_id: kit.id,
			name: kit.name,
			match_mode: 'all',
			conditions: [],
			children: [],
			disabled: false
		};
	}

	async function handleCreate(e: Event) {
		e.preventDefault();
		if (creating || !name.trim()) return;
		if (profileType === 'set' && selectedSets.length === 0) {
			error = 'Add at least one set.';
			return;
		}

		creating = true;
		error = null;
		try {
			if (profileType === 'set') {
				// Each set becomes a kit of its own, and a kit bin for each.
				const kits: Kit[] = [];
				for (const set of selectedSets) {
					kits.push(
						await api.createKitFromSet({ set_num: set.set_num, include_spares: includeSpares, name: set.name })
					);
				}
				const profile = await api.createSortingProfile({
					name: name.trim(),
					visibility: 'private',
					rules: kits.map(makeKitRule)
				});
				goto(`/profiles/${profile.id}/edit`);
			} else {
				const profile = await api.createSortingProfile({ name: name.trim(), visibility: 'private' });
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
	<title>New profile - Hive</title>
</svelte:head>

<div class="mx-auto flex w-full max-w-xl flex-col gap-(--gap-panels)">
	<div>
		<Button href="/profiles" size="sm" variant="ghost" icon={ArrowLeft}>Profiles</Button>
	</div>

	<PageHeader title="New sorting profile" description="Choose what kind of profile it is, then name it." />

	{#if error}
		<Alert tone="danger">{error}</Alert>
	{/if}

	<Panel>
		<form id="new-profile" onsubmit={handleCreate} class="flex flex-col gap-5">
			<RadioGroup
				name="profile-type"
				label="Profile type"
				bind:value={profileType}
				options={[
					{ value: 'rule', label: 'Rule based', help: 'Sort by what parts are: category, color, price.' },
					{ value: 'set', label: 'Kit based', help: 'Collect the parts of particular LEGO sets from mixed parts.' }
				]}
			/>

			<Field label="Name" for="profile-name">
				<Input
					id="profile-name"
					bind:value={name}
					placeholder={profileType === 'set' ? 'For example: UCS collection' : 'For example: my Technic sorter'}
				/>
			</Field>

			{#if profileType === 'rule'}
				{#if !hasOpenRouter}
					<Alert tone="warning" title="The assistant needs an OpenRouter key">
						You can still create the profile and write its rules yourself, or add a key first.
						{#snippet actions()}
							<Button href="/settings" size="sm">Settings</Button>
						{/snippet}
					</Alert>
				{/if}
			{:else}
				<div class="flex flex-col gap-2">
					<div class="text-sm font-medium text-ink">Sets</div>
					<SetSearch onSelect={addSet} />
				</div>

				{#if selectedSets.length > 0}
					<div class="flex flex-col gap-1">
						<div class="text-sm font-medium text-ink">
							Chosen sets <span class="num text-ink-muted">{selectedSets.length}</span>
						</div>
						<ul class="divide-y divide-line">
							{#each selectedSets as set (set.set_num)}
								<li class="flex items-center gap-3 py-2">
									{#if set.img_url}
										<img src={set.img_url} alt="" class="size-8 object-contain" />
									{:else}
										<span class="flex size-8 items-center justify-center rounded-control bg-well text-xs text-ink-muted">?</span>
									{/if}
									<span class="min-w-0 flex-1 text-sm">
										<span class="block truncate font-medium text-ink">{set.name}</span>
										<span class="block text-ink-muted"
											><span class="font-mono">{set.set_num}</span>, <span class="num">{set.num_parts}</span> parts</span
										>
									</span>
									<Button variant="ghost" size="sm" onclick={() => removeSet(set.set_num)}>Remove</Button>
								</li>
							{/each}
						</ul>
					</div>
				{/if}

				<Checkbox id="include-spares" bind:checked={includeSpares}>Include spare parts</Checkbox>
			{/if}
		</form>
		{#snippet footer()}
			<Button href="/profiles" variant="ghost">Cancel</Button>
			<Button
				type="submit"
				form="new-profile"
				variant="primary"
				loading={creating}
				disabled={!name.trim() || (profileType === 'set' && selectedSets.length === 0)}
				>Create and open the editor</Button
			>
		{/snippet}
	</Panel>
</div>
