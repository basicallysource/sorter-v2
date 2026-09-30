<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type SortingProfileSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Funnel from '@lucide/svelte/icons/funnel';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';

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

<PageHeader title="Sorting profiles" description="Build, share, fork and assign sorting logic across your machines.">
	{#snippet actions()}
		<Button variant="primary" icon={Plus} loading={creating} onclick={createProfile}>New profile</Button>
	{/snippet}
</PageHeader>

{#if error && !deleteTarget}
	<Alert tone="danger">{error}</Alert>
{/if}

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if profiles.length === 0}
	<Panel>
		<EmptyState icon={Funnel} title="No profiles yet">
			A profile is the rules a machine sorts by: which parts go to which bin.
			{#snippet action()}
				<Button variant="primary" icon={Plus} loading={creating} onclick={createProfile}>New profile</Button>
			{/snippet}
		</EmptyState>
	</Panel>
{:else}
	<div class="grid gap-(--gap-panels) sm:grid-cols-2 xl:grid-cols-3">
		{#each profiles as profile (profile.id)}
			{@const rules = profile.latest_version?.rules_summary ?? []}
			{@const activeRules = rules.filter((r) => !r.disabled)}
			<Card
				href={profile.is_owner ? `/profiles/${profile.id}/edit` : `/profiles/${profile.id}`}
				label={profile.name}
				padded={false}
				class="overflow-hidden"
			>
				<div class="flex items-start justify-between gap-2 px-(--pad-panel) pt-4 pb-3">
					<div class="min-w-0">
						<h2 class="flex items-center gap-2 font-semibold text-ink">
							<span
								class="size-2 shrink-0 rounded-full {profile.visibility === 'public' ? 'bg-info' : 'bg-ink-faint'}"
								title={profile.visibility === 'public' ? 'Public' : 'Private'}
							></span>
							<span class="truncate">{profile.name}</span>
						</h2>
						{#if profile.description}
							<p class="mt-0.5 truncate text-sm text-ink-muted">{profile.description}</p>
						{/if}
					</div>
					<div class="flex shrink-0 items-center gap-1.5">
						{#if profile.source}<Badge tone="warning">Fork</Badge>{/if}
						<Badge><span class="num">v{profile.latest_version_number}</span></Badge>
					</div>
				</div>

				{#if activeRules.length > 0}
					<ul class="flex flex-col gap-1.5 border-t border-line px-(--pad-panel) py-3">
						{#each activeRules.slice(0, 6) as rule, i (i)}
							<li class="flex items-center gap-2 text-sm">
								{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
									<img src={rule.set_meta.img_url} alt="" class="size-5 shrink-0 object-contain" />
								{:else}
									<Funnel size={14} class="shrink-0 text-ink-muted" />
								{/if}
								<span class="truncate text-ink">{rule.name}</span>
								{#if rule.rule_type === 'set' && rule.set_num}
									<span class="shrink-0 font-mono text-sm text-ink-muted">{rule.set_num}</span>
								{:else if rule.condition_count > 0}
									<span class="num shrink-0 text-ink-muted"
										>{rule.condition_count} condition{rule.condition_count !== 1 ? 's' : ''}</span
									>
								{/if}
								{#if rule.child_count > 0}
									<span class="num shrink-0 text-ink-muted">+{rule.child_count} nested</span>
								{/if}
							</li>
						{/each}
						{#if activeRules.length > 6}
							<li class="text-sm text-ink-muted">{activeRules.length - 6} more rules</li>
						{/if}
					</ul>
				{:else if rules.length === 0}
					<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">No rules yet.</p>
				{/if}

				<div
					class="mt-auto flex items-center justify-between gap-2 border-t border-line px-(--pad-panel) py-2 text-sm text-ink-muted"
				>
					<span class="flex min-w-0 flex-wrap items-center gap-x-3">
						<span class="num">{profile.latest_version?.compiled_part_count ?? 0} parts</span>
						{#if profile.fork_count > 0}<span class="num">{profile.fork_count} forks</span>{/if}
						{#if !profile.is_owner}
							<span class="truncate">By {profile.owner.display_name ?? profile.owner.github_login ?? '?'}</span>
						{/if}
					</span>
					<span class="flex shrink-0 items-center gap-1.5">
						{#each profile.tags.slice(0, 3) as tag (tag)}
							<Badge>{tag}</Badge>
						{/each}
						{#if profile.is_owner}
							<Button variant="ghost" size="sm" icon={Trash2} label="Delete profile" onclick={() => (deleteTarget = profile)} />
						{/if}
					</span>
				</div>
			</Card>
		{/each}
	</div>
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
