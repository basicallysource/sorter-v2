<!--
	Every saved version of the profile, newest first: who saved it and when, its
	note, and its first bins by picture. "View" opens a version's bins in place,
	"Restore" saves it again as the newest version, and "Fork" starts a profile of
	its own from it.
-->
<script lang="ts">
	import GitFork from '@lucide/svelte/icons/git-fork';
	import { api, type SortingProfileDetail, type SortingProfileVersion } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import PartImage from '$lib/components/PartImage.svelte';
	import ProfileBin from '$lib/components/ProfileBin.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { savedLine } from '$lib/profile-display';
	import { formatDate } from '$lib/time';
	import { plural } from './rules';

	let {
		profile,
		restoringId,
		onrestore,
		onfork
	}: {
		profile: SortingProfileDetail;
		restoringId: string | null;
		onrestore: (versionId: string) => void;
		onfork: (versionId: string) => void;
	} = $props();

	const SHOWN_BINS = 40;

	const versions = $derived([...profile.versions].sort((a, b) => b.version_number - a.version_number));
	const currentId = $derived(profile.current_version?.id ?? null);

	let viewingId = $state<string | null>(null);
	let viewed = $state.raw<SortingProfileVersion | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let showAllBins = $state(false);

	async function view(id: string) {
		if (viewingId === id) {
			viewingId = null;
			viewed = null;
			return;
		}
		viewingId = id;
		viewed = null;
		error = null;
		showAllBins = false;
		loading = true;
		try {
			const detail = await api.getSortingProfile(profile.id, id);
			if (viewingId === id) viewed = detail.current_version;
		} catch (e) {
			if (viewingId === id) error = (e as { error?: string })?.error ?? 'The version could not be loaded.';
		}
		if (viewingId === id) loading = false;
	}

	const viewedOrder = $derived(viewed?.category_order ?? []);
	const shownOrder = $derived(showAllBins ? viewedOrder : viewedOrder.slice(0, SHOWN_BINS));
</script>

{#if versions.length === 0}
	<p class="p-6 text-center text-sm text-ink-muted">No versions yet. Save one to keep this draft.</p>
{:else}
	<ul class="divide-y divide-line">
		{#each versions as version (version.id)}
			{@const isCurrent = version.id === currentId}
			<li class="flex flex-col gap-2 py-3 {isCurrent ? 'bg-primary-soft' : ''}">
				<div class="flex items-center justify-between gap-2 px-(--pad-panel)">
					<div class="flex flex-wrap items-center gap-2">
						<span class="num font-medium {isCurrent ? 'text-primary-ink' : 'text-ink'}">v{version.version_number}</span>
						{#if isCurrent}<Badge tone="primary">Latest</Badge>{/if}
						{#if version.is_published}<Badge tone="success">Published</Badge>{/if}
						{#if version.label}<Badge>{version.label}</Badge>{/if}
					</div>
				</div>
				<p class="px-(--pad-panel) text-sm text-ink-muted" title={formatDate(version.created_at)}>
					{savedLine(version)}
				</p>
				{#if version.change_note}
					<p class="px-(--pad-panel) text-sm text-ink">{version.change_note}</p>
				{/if}
				<p class="px-(--pad-panel) text-sm text-ink-muted">
					{plural(version.compiled_part_count, 'part')} in their own bins
				</p>
				{#if version.bins.length > 0}
					<div class="flex items-center gap-1.5 px-(--pad-panel)" aria-hidden="true">
						{#each version.bins.slice(0, 10) as bin (bin.id)}
							<PartImage src={bin.image_url} class="size-7" />
						{/each}
					</div>
				{/if}
				<div class="flex flex-wrap items-center gap-2 px-(--pad-panel)">
					<Button size="sm" onclick={() => void view(version.id)}>
						{viewingId === version.id ? 'Hide' : 'View'}
					</Button>
					{#if !isCurrent}
						<Button
							size="sm"
							loading={restoringId === version.id}
							disabled={restoringId !== null}
							onclick={() => onrestore(version.id)}
						>
							Restore
						</Button>
					{/if}
					<Button size="sm" variant="ghost" icon={GitFork} onclick={() => onfork(version.id)}>Fork</Button>
				</div>

				{#if viewingId === version.id}
					<div class="mt-1 border-t border-line">
						{#if loading}
							<p class="flex items-center gap-2 px-(--pad-panel) py-3 text-sm text-ink-muted">
								<Spinner size={14} />Loading the bins
							</p>
						{:else if error}
							<div class="p-(--pad-panel)"><Alert tone="danger">{error}</Alert></div>
						{:else if viewed}
							<ul class="divide-y divide-line">
								{#each shownOrder as id (id)}
									{#if viewed.categories[id]}
										<li><ProfileBin layout="row" bin={viewed.categories[id]} /></li>
									{/if}
								{/each}
							</ul>
							{#if viewedOrder.length > SHOWN_BINS}
								<div class="border-t border-line px-(--pad-panel) py-2">
									<Button variant="ghost" size="sm" onclick={() => (showAllBins = !showAllBins)}>
										{showAllBins ? 'Show fewer' : `Show all ${viewedOrder.length.toLocaleString('en-US')} bins`}
									</Button>
								</div>
							{/if}
						{/if}
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
