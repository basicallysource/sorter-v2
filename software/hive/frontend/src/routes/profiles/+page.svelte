<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type SortingProfileSummary } from '$lib/api';
	import { plural } from '$lib/profile-display';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProfileBin from '$lib/components/ProfileBin.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import Funnel from '@lucide/svelte/icons/funnel';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	type Tab = 'mine' | 'library' | 'defaults' | 'discover';
	const tabNames: Tab[] = ['mine', 'library', 'defaults', 'discover'];

	// How many bins a card lists: the first ones say what the profile is about.
	const BINS_SHOWN = 5;

	let lists = $state<Partial<Record<Tab, SortingProfileSummary[]>>>({});
	let loadingTab = $state<Tab | null>(null);
	let tab = $state<Tab>('mine');
	let error = $state<string | null>(null);
	let creating = $state(false);
	let deleteTarget = $state<SortingProfileSummary | null>(null);
	let deleting = $state(false);
	let started = $state(false);

	async function loadTab(which: Tab) {
		if (lists[which]) return;
		loadingTab = which;
		try {
			lists[which] = await api.getProfiles({ scope: which });
		} catch (e: any) {
			error = e.error || 'Failed to load sorting profiles';
		} finally {
			if (loadingTab === which) loadingTab = null;
		}
	}

	// Yours and Hive's defaults load first: a person with no profiles of
	// their own opens on the defaults.
	$effect(() => {
		void (async () => {
			loadingTab = 'mine';
			await Promise.all([loadTab('mine'), loadTab('defaults')]);
			const asked = page.url.searchParams.get('tab');
			tab = tabNames.find((name) => name === asked) ?? ((lists.mine?.length ?? 0) > 0 ? 'mine' : 'defaults');
			started = true;
			void loadTab(tab);
		})();
	});

	function chooseTab(next: Tab) {
		tab = next;
		void loadTab(next);
		const url = new URL(page.url);
		url.searchParams.set('tab', next);
		void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	// Other people's public profiles: Hive's own and yours are in their tabs.
	function listed(which: Tab): SortingProfileSummary[] | undefined {
		const list = lists[which];
		return which === 'discover' ? list?.filter((p) => !p.is_default && !p.is_owner) : list;
	}

	const tabItems = $derived([
		{ value: 'mine' as Tab, label: 'Yours', count: listed('mine')?.length },
		{ value: 'library' as Tab, label: 'Library', count: listed('library')?.length },
		{ value: 'defaults' as Tab, label: 'Hive defaults', count: listed('defaults')?.length },
		{ value: 'discover' as Tab, label: 'Public', count: listed('discover')?.length }
	]);

	const profiles = $derived(listed(tab) ?? []);

	const empty = $derived(
		{
			mine: {
				title: 'No profiles yet',
				text: 'A profile is the rules a machine sorts by: which parts go to which bin.'
			},
			library: {
				title: 'Your library is empty',
				text: "Save one of Hive's defaults or a public profile and it is kept here."
			},
			defaults: { title: 'No defaults', text: 'Hive has no default profiles.' },
			discover: {
				title: 'No public profiles yet',
				text: 'Profiles other people make public show up here.'
			}
		}[tab]
	);

	async function createProfile() {
		creating = true;
		error = null;
		try {
			const profile = await api.createSortingProfile({ name: 'Untitled profile', visibility: 'private' });
			goto(`/profiles/${profile.id}/edit?new=1`);
		} catch (e: any) {
			error = e.error || 'Failed to create profile';
			creating = false;
		}
	}

	async function confirmDelete() {
		if (!deleteTarget) return;
		deleting = true;
		error = null;
		try {
			await api.deleteSortingProfile(deleteTarget.id);
			const gone = deleteTarget.id;
			for (const name of tabNames) {
				const list = lists[name];
				if (list) lists[name] = list.filter((p) => p.id !== gone);
			}
			deleteTarget = null;
		} catch (e: any) {
			error = e.error || 'Failed to delete profile';
		} finally {
			deleting = false;
		}
	}

	// The bins a card lists, as the bin component reads them. A color bin is
	// the one with a color, so the others must not carry the key at all. A
	// version saved before bins were described has only its rules' names.
	function binsOf(profile: SortingProfileSummary) {
		const version = profile.latest_version;
		if (!version) return [];
		if (version.bins.length > 0) {
			return version.bins.map((bin) => ({
				id: bin.id,
				bin: {
					name: bin.name ?? 'Unnamed',
					kind: bin.kind,
					image_url: bin.image_url,
					part_count: bin.part_count,
					...(bin.rgb ? { rgb: bin.rgb } : {})
				}
			}));
		}
		return version.rules_summary
			.filter((rule) => !rule.disabled)
			.map((rule, i) => ({ id: String(i), bin: { name: rule.name } }));
	}

	function ruleCount(profile: SortingProfileSummary) {
		return (profile.latest_version?.rules_summary ?? []).filter((rule) => !rule.disabled).length;
	}
</script>

<svelte:head>
	<title>Profiles - Hive</title>
</svelte:head>

<PageHeader
	title="Sorting profiles"
	description="A profile says where each piece goes. Make your own, or start from one of Hive's."
>
	{#snippet actions()}
		<Button variant="primary" icon={Plus} loading={creating} onclick={createProfile}>New profile</Button>
	{/snippet}
</PageHeader>

{#if error && !deleteTarget}
	<Alert tone="danger">{error}</Alert>
{/if}

{#if !started}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else}
	<Tabs label="Profiles" value={tab} items={tabItems} onchange={chooseTab} />

	{#if !lists[tab] && loadingTab === tab}
		<div class="flex justify-center p-8"><Spinner size={32} /></div>
	{:else if profiles.length === 0}
		<Panel>
			<EmptyState icon={Funnel} title={empty.title}>
				{empty.text}
				{#snippet action()}
					{#if tab === 'mine'}
						<Button variant="primary" icon={Plus} loading={creating} onclick={createProfile}>New profile</Button>
					{:else if tab === 'library'}
						<Button onclick={() => chooseTab('defaults')}>See Hive's defaults</Button>
					{/if}
				{/snippet}
			</EmptyState>
		</Panel>
	{:else}
		<div class="grid gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3">
			{#each profiles as profile (profile.id)}
				{@const bins = binsOf(profile)}
				{@const rules = ruleCount(profile)}
				<Card href={`/profiles/${profile.id}`} label={profile.name} padded={false} class="overflow-hidden">
					<div class="flex flex-col gap-1.5 px-(--pad-panel) pt-4 pb-3">
						<div class="flex items-start justify-between gap-3">
							<h2 class="min-w-0 truncate text-base font-semibold text-ink">{profile.name}</h2>
							<Badge><span class="num">v{profile.latest_version_number}</span></Badge>
						</div>
						{#if profile.description}
							<p class="line-clamp-2 text-sm text-ink-muted">{profile.description}</p>
						{/if}
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
							<span class="truncate">By {profile.owner.display_name ?? profile.owner.github_login ?? 'unknown'}</span>
							{#if profile.is_default}<Badge tone="info">Hive default</Badge>{/if}
							{#if profile.source}<Badge tone="warning">Fork</Badge>{/if}
							{#if profile.is_owner && tab !== 'mine'}<Badge>Yours</Badge>{/if}
							{#if profile.is_owner}<Badge>{sentence(profile.visibility)}</Badge>{/if}
							<span class="num">{rules === 0 ? 'No rules' : plural(rules, 'rule')}</span>
						</div>
					</div>

					{#if bins.length > 0}
						<ul class="divide-y divide-line border-t border-line">
							{#each bins.slice(0, BINS_SHOWN) as item (item.id)}
								<li><ProfileBin layout="row" bin={item.bin} /></li>
							{/each}
						</ul>
					{:else}
						<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">No rules yet.</p>
					{/if}

					{#if profile.is_owner}
						<div class="mt-auto flex justify-end border-t border-line px-(--pad-panel) py-2">
							<Button variant="ghost" size="sm" icon={Trash2} label="Delete profile" onclick={() => (deleteTarget = profile)} />
						</div>
					{/if}
				</Card>
			{/each}
		</div>
	{/if}
{/if}

<Modal
	open={deleteTarget !== null}
	title="Delete profile"
	size="sm"
	onclose={() => {
		deleteTarget = null;
		error = null;
	}}
>
	<p class="text-sm text-ink-muted">
		Delete <span class="font-medium text-ink">{deleteTarget?.name}</span>? This cannot be undone.
	</p>
	{#if error}<Alert tone="danger" class="mt-3">{error}</Alert>{/if}
	{#snippet footer()}
		<Button variant="ghost" disabled={deleting} onclick={() => (deleteTarget = null)}>Cancel</Button>
		<Button variant="danger" loading={deleting} onclick={confirmDelete}>Delete profile</Button>
	{/snippet}
</Modal>
