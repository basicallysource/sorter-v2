<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type ProfileBin as ApiBin,
		type ProfileHead,
		type SortingProfileDetail,
		type SortingProfileVersion,
		type SortingProfileVersionSummary
	} from '$lib/api';
	import { plural, savedBy, savedLine } from '$lib/profile-display';
	import { sentence } from '$lib/text';
	import { relativeTime } from '$lib/time';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProfileBin from '$lib/components/ProfileBin.svelte';
	import Select from '$lib/components/Select.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import KitProgress from '$lib/components/profile/KitProgress.svelte';
	import RoutePanel from '$lib/components/profile/RoutePanel.svelte';
	import VersionList from '$lib/components/profile/VersionList.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import BookmarkPlus from '@lucide/svelte/icons/bookmark-plus';
	import Check from '@lucide/svelte/icons/check';
	import Funnel from '@lucide/svelte/icons/funnel';
	import GitFork from '@lucide/svelte/icons/git-fork';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';

	type Kind = 'rule' | 'kit' | 'fallback' | 'default';
	type Entry = { id: string; bin: ApiBin; kind: Kind; number?: number; warnings: string[] };

	let loading = $state(true);
	let profile = $state<SortingProfileDetail | null>(null);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	// The version on the page: null follows the latest one.
	let viewing = $state<string | null>(null);
	let settingsName = $state('');
	let settingsDescription = $state('');
	let settingsVisibility = $state<'private' | 'unlisted' | 'public'>('private');
	let settingsTags = $state('');
	let savingSettings = $state(false);
	let libraryBusy = $state(false);
	let forking = $state(false);
	let publishingId = $state<string | null>(null);
	let showDeleteModal = $state(false);
	let deletingProfile = $state(false);

	// A change made elsewhere (an assistant through the API, the editor in
	// another tab), and what it changed, until it is dismissed.
	let update = $state<{
		number: number;
		following: boolean;
		at: string;
		by: string | null;
		note: string | null;
		changes: string | null;
	} | null>(null);
	// Bins to draw attention to for a few seconds: where a piece landed, or
	// what a change touched.
	let flashed = $state<Set<string>>(new Set());
	let flashTimer: ReturnType<typeof setTimeout> | undefined;
	// The clock for "just now" on the notice.
	let tick = $state(0);
	// How many fallback bins are listed, and the filter on them.
	let fallbackShown = $state(10);
	let fallbackFilter = $state('');

	// What the poll compares the profile's head against.
	let knownVersionId: string | null = null;
	let knownUpdatedAt: string | null = null;

	const profileId = $derived(page.params.id ?? '');
	const cv = $derived(profile?.current_version ?? null);
	const versions = $derived(profile?.versions ?? []);
	const latest = $derived(versions[0] ?? null);
	const viewingOlder = $derived(Boolean(cv && latest && cv.id !== latest.id));
	const parsedTags = $derived(
		settingsTags
			.split(',')
			.map((t) => t.trim())
			.filter(Boolean)
	);

	function kindOf(id: string, bin: Partial<ApiBin>, defaultId: string): Kind {
		if (bin.kind) return bin.kind;
		// A version saved before bins were described has only names.
		if (id === defaultId) return 'default';
		if (/^(bl|rb)_\d+$/.test(id) || id.startsWith('color_')) return 'fallback';
		return 'rule';
	}

	// Every bin of the version: in its order, then any the order leaves out
	// (a profile that sorts the rest by color has a bin per color, none of
	// them in the order).
	function entriesOf(version: SortingProfileVersion | null): Entry[] {
		if (!version) return [];
		const categories = version.categories ?? {};
		const order = version.category_order ?? [];
		const ordered = new Set(order);
		const ids = [...order.filter((id) => id in categories), ...Object.keys(categories).filter((id) => !ordered.has(id))];
		const warned = new Map<string, string[]>();
		for (const warning of version.warnings ?? []) {
			if (warning.rule_id) warned.set(warning.rule_id, [...(warned.get(warning.rule_id) ?? []), warning.message]);
		}
		let place = 0;
		return ids.map((id) => {
			const bin: ApiBin = { ...categories[id] };
			if (typeof bin.name !== 'string') bin.name = id;
			const kind = kindOf(id, bin, version.default_category_id);
			const numbered = kind === 'rule' || kind === 'kit';
			return { id, bin, kind, number: numbered ? ++place : undefined, warnings: warned.get(id) ?? [] };
		});
	}

	const entries = $derived(entriesOf(cv));
	const ruleEntries = $derived(entries.filter((e) => e.kind === 'rule' || e.kind === 'kit'));
	const fallbackEntries = $derived(entries.filter((e) => e.kind === 'fallback'));
	const defaultEntry = $derived(entries.find((e) => e.kind === 'default') ?? null);
	const entryById = $derived(new Map(entries.map((e) => [e.id, e])));
	const hasKits = $derived(entries.some((e) => e.kind === 'kit'));
	// Warnings that belong to no bin.
	const looseWarnings = $derived((cv?.warnings ?? []).filter((w) => !w.rule_id || !entryById.has(w.rule_id)));

	const fallbackBy = $derived.by(() => {
		const flags = cv?.fallback_mode;
		if (flags?.bricklink_categories) return 'bricklink';
		if (flags?.rebrickable_categories) return 'rebrickable';
		if (flags?.by_color) return 'color';
		const first = fallbackEntries[0]?.id ?? '';
		if (first.startsWith('bl_')) return 'bricklink';
		if (first.startsWith('rb_')) return 'rebrickable';
		return first ? 'color' : null;
	});
	const fallbackText = $derived(
		{
			bricklink: 'Pieces no rule takes are sorted by their BrickLink category, or go to Everything else when they have none.',
			rebrickable: 'Pieces no rule takes are sorted by their Rebrickable category, or go to Everything else when they have none.',
			color: 'Pieces no rule takes are sorted by their color.',
			none: 'Pieces no rule takes all go to Everything else.'
		}[fallbackBy ?? 'none']
	);
	const fallbackMatches = $derived.by(() => {
		const needle = fallbackFilter.trim().toLowerCase();
		return needle ? fallbackEntries.filter((e) => e.bin.name.toLowerCase().includes(needle)) : fallbackEntries;
	});

	const originLine = $derived(cv ? savedLine(cv) : '');

	// --- Loading ------------------------------------------------------------

	function apply(d: SortingProfileDetail, resetSettings: boolean) {
		profile = d;
		knownVersionId = d.versions[0]?.id ?? null;
		knownUpdatedAt = d.updated_at;
		if (resetSettings) {
			settingsName = d.name;
			settingsDescription = d.description ?? '';
			settingsVisibility = d.visibility;
			settingsTags = d.tags.join(', ');
		}
	}

	// The first load of a profile, honouring a version asked for in the address.
	async function loadFirst(id: string) {
		loading = true;
		error = null;
		try {
			let d = await api.getSortingProfile(id);
			const asked = Number(page.url.searchParams.get('version'));
			const match = asked ? d.versions.find((v) => v.version_number === asked) : undefined;
			if (match && match.id !== d.current_version?.id) {
				d = await api.getSortingProfile(id, match.id);
				viewing = match.id;
			}
			apply(d, true);
		} catch (e: any) {
			error = e.error || 'Failed to load profile';
		} finally {
			loading = false;
		}
	}

	// Load again without the page noticing: nothing is torn down, so scroll
	// and what is open stay where they are.
	async function reload(resetSettings = false) {
		try {
			apply(await api.getSortingProfile(profileId, viewing ?? undefined), resetSettings);
		} catch (e: any) {
			error = e.error || 'Failed to load profile';
		}
	}

	$effect(() => {
		const id = profileId;
		if (!id) return;
		untrack(() => {
			profile = null;
			viewing = null;
			update = null;
			flashed = new Set();
			fallbackShown = 10;
			fallbackFilter = '';
		});
		void loadFirst(id);
	});

	// --- Live updates ---------------------------------------------------------

	const ready = $derived(profile !== null);

	$effect(() => {
		const id = profileId;
		if (!id || !ready) return;
		let stopped = false;
		let asking = false;

		async function check() {
			if (asking || document.visibilityState !== 'visible') return;
			asking = true;
			try {
				const head = await api.getSortingProfileHead(id);
				if (stopped) return;
				const moved = head.latest_version_id !== knownVersionId;
				const touched =
					knownUpdatedAt !== null && new Date(head.updated_at).getTime() !== new Date(knownUpdatedAt).getTime();
				if (moved || touched) await refresh(head, moved);
			} catch {
				/* offline, or signed out: ask again next time */
			} finally {
				asking = false;
			}
		}

		const timer = setInterval(() => void check(), 3000);
		const onVisible = () => {
			if (document.visibilityState === 'visible') void check();
		};
		document.addEventListener('visibilitychange', onVisible);
		return () => {
			stopped = true;
			clearInterval(timer);
			document.removeEventListener('visibilitychange', onVisible);
		};
	});

	async function refresh(head: ProfileHead, newVersion: boolean) {
		const before = untrack(() => entries);
		const following = untrack(() => viewing === null);
		const d = await api.getSortingProfile(profileId, untrack(() => viewing) ?? undefined);
		apply(d, false);
		if (!newVersion) return;
		const saved = d.versions[0];
		const changed = following ? changesBetween(before, entriesOf(d.current_version)) : null;
		update = {
			number: head.latest_version_number,
			following,
			at: head.latest_version_created_at ?? new Date().toISOString(),
			by: savedBy(head.created_via, head.created_via_key_name),
			note: saved?.change_note ?? null,
			changes: changed ? changed.summary : null
		};
		if (changed) flash(changed.ids);
	}

	// Which rules and kits a new version added, removed or changed.
	function changesBetween(before: Entry[], after: Entry[]): { summary: string | null; ids: string[] } {
		const sign = (e: Entry) => JSON.stringify([e.bin.name, e.bin.conditions, e.bin.part_count, e.bin.kit, e.bin.image_url]);
		const rules = (list: Entry[]) => new Map(list.filter((e) => e.kind === 'rule' || e.kind === 'kit').map((e) => [e.id, sign(e)]));
		const was = rules(before);
		const now = rules(after);
		const added = [...now.keys()].filter((id) => !was.has(id));
		const removed = [...was.keys()].filter((id) => !now.has(id));
		const changed = [...now.keys()].filter((id) => was.has(id) && was.get(id) !== now.get(id));
		const parts = [
			added.length ? `${plural(added.length, 'category', 'categories')} added` : null,
			changed.length ? `${plural(changed.length, 'category', 'categories')} changed` : null,
			removed.length ? `${plural(removed.length, 'category', 'categories')} removed` : null
		].filter(Boolean);
		return { summary: parts.length ? `${parts.join(', ')}.` : null, ids: [...added, ...changed] };
	}

	function flash(ids: string[]) {
		clearTimeout(flashTimer);
		flashed = new Set(ids);
		flashTimer = setTimeout(() => (flashed = new Set()), 6000);
	}

	$effect(() => {
		if (!update) return;
		const timer = setInterval(() => tick++, 20000);
		return () => clearInterval(timer);
	});

	$effect(() => () => clearTimeout(flashTimer));

	// "just now", read again as the clock ticks.
	function ago(iso: string) {
		void tick;
		return relativeTime(iso);
	}

	// --- Actions ----------------------------------------------------------------

	async function pick(version: SortingProfileVersionSummary) {
		viewing = version.id === latest?.id ? null : version.id;
		update = null;
		await reload();
		const url = new URL(page.url);
		if (viewing === null) url.searchParams.delete('version');
		else url.searchParams.set('version', String(version.version_number));
		void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}

	async function saveSettings() {
		if (!profile) return;
		savingSettings = true;
		error = null;
		success = null;
		try {
			const u = await api.updateSortingProfile(profile.id, {
				name: settingsName,
				description: settingsDescription || null,
				visibility: settingsVisibility,
				tags: parsedTags
			});
			profile = { ...profile, ...u, current_version: profile.current_version, versions: profile.versions };
			knownUpdatedAt = u.updated_at;
			success = 'Settings saved.';
		} catch (e: any) {
			error = e.error || 'Failed to save settings';
		} finally {
			savingSettings = false;
		}
	}

	async function toggleLibrary() {
		if (!profile) return;
		libraryBusy = true;
		error = null;
		success = null;
		try {
			if (profile.saved_in_library) {
				await api.removeSortingProfileFromLibrary(profile.id);
				success = 'Removed from your library.';
			} else {
				await api.saveSortingProfileToLibrary(profile.id);
				success = 'Saved to your library.';
			}
			await reload();
		} catch (e: any) {
			error = e.error || 'Failed to update library';
		} finally {
			libraryBusy = false;
		}
	}

	async function forkProfile() {
		if (!profile) return;
		forking = true;
		error = null;
		try {
			const fork = await api.forkSortingProfile(
				profile.id,
				{ add_to_library: true, name: `${profile.name} (Fork)` },
				cv?.id
			);
			goto(`/profiles/${fork.id}/edit`);
		} catch (e: any) {
			error = e.error || 'Failed to fork profile';
		} finally {
			forking = false;
		}
	}

	async function publish(version: SortingProfileVersionSummary) {
		if (!profile) return;
		publishingId = version.id;
		error = null;
		success = null;
		try {
			await api.publishSortingProfileVersion(profile.id, version.id);
			await reload();
			success = `Published v${version.version_number}. Other people's machines can use it.`;
		} catch (e: any) {
			error = e.error || 'Failed to publish';
		} finally {
			publishingId = null;
		}
	}

	async function deleteProfile() {
		if (!profile) return;
		deletingProfile = true;
		error = null;
		try {
			await api.deleteSortingProfile(profile.id);
			goto('/profiles');
		} catch (e: any) {
			error = e.error || 'Failed to delete profile';
		} finally {
			deletingProfile = false;
		}
	}

	function removeTag(tag: string) {
		settingsTags = parsedTags.filter((t) => t !== tag).join(', ');
	}

	// The bin a piece was routed to, as the route box shows it.
	function destination(id: string, name: string) {
		const entry = entryById.get(id);
		if (entry) return { bin: entry.bin, number: entry.number };
		return { bin: { name, kind: kindOf(id, {}, cv?.default_category_id ?? 'misc') } as ApiBin };
	}

	// Scroll to a bin and mark it for a moment, opening the fallback list
	// first when the bin is in it.
	async function showBin(id: string) {
		if (entryById.get(id)?.kind === 'fallback') {
			fallbackFilter = '';
			const at = fallbackEntries.findIndex((e) => e.id === id);
			if (at >= fallbackShown) fallbackShown = at + 1;
		}
		flash([id]);
		await new Promise((resolve) => requestAnimationFrame(resolve));
		document
			.querySelector(`[data-bin="${CSS.escape(id)}"]`)
			?.scrollIntoView({ block: 'center', behavior: 'smooth' });
	}
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
		<div class="flex flex-col gap-2">
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-ink-muted">
				<span>By {profile.owner.display_name ?? profile.owner.github_login ?? 'unknown'}</span>
				{#if profile.is_default}<Badge tone="info">Hive default</Badge>{/if}
				{#if profile.is_owner}<Badge>{sentence(profile.visibility)}</Badge>{/if}
				{#if profile.source}
					<span>
						Forked from
						<a href="/profiles/{profile.source.profile_id}" class="text-primary-ink hover:underline"
							>{profile.source.profile_name}</a
						>{#if profile.source.version_number}<span class="num ml-1">v{profile.source.version_number}</span>{/if}
					</span>
				{/if}
				{#each profile.tags.filter((t) => !(profile!.is_default && t === 'default')) as tag (tag)}<Badge>{tag}</Badge>{/each}
				{#if profile.library_count > 0}<span class="num">{plural(profile.library_count, 'save')}</span>{/if}
				{#if profile.fork_count > 0}<span class="num">{plural(profile.fork_count, 'fork')}</span>{/if}
			</div>
			{#if cv}
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
					<Badge><span class="num">v{cv.version_number}</span></Badge>
					<span>{originLine}</span>
					{#if profile.is_owner && !cv.is_published}<Badge>Not published</Badge>{/if}
				</div>
			{/if}
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

	{#if error}<Alert tone="danger">{error}</Alert>{/if}
	{#if success}<Alert tone="success">{success}</Alert>{/if}

	{#if update}
		<Alert tone="info" title="Updated to v{update.number} {ago(update.at)}{update.by ? ` ${update.by}` : ''}">
			{#if update.following}
				{#if update.changes}{update.changes}{/if}
			{:else}
				You are looking at v{cv?.version_number}. v{update.number} is the latest.
			{/if}
			{#if update.note}<div class="text-ink-muted">{update.note}</div>{/if}
			{#snippet actions()}
				{#if !update!.following && latest}
					<Button size="sm" onclick={() => void pick(latest!)}>Show v{latest.version_number}</Button>
				{/if}
				<Button size="sm" variant="ghost" icon={X} label="Dismiss" onclick={() => (update = null)} />
			{/snippet}
		</Alert>
	{:else if viewingOlder && latest && cv}
		<Alert tone="info" title="You are looking at v{cv.version_number}">
			The latest is v{latest.version_number}.
			{#snippet actions()}
				<Button size="sm" onclick={() => void pick(latest!)}>Show v{latest!.version_number}</Button>
			{/snippet}
		</Alert>
	{/if}

	{#if looseWarnings.length > 0}
		<Alert tone="warning" title={looseWarnings.length === 1 ? 'Something to check' : 'Some things to check'}>
			<ul class="flex flex-col gap-1">
				{#each looseWarnings as warning, i (i)}<li>{warning.message}</li>{/each}
			</ul>
		</Alert>
	{/if}

	{#if !cv}
		<Panel>
			<EmptyState icon={Funnel} title="No versions yet">
				This profile has not been saved.
				{#snippet action()}
					{#if profile!.is_owner}
						<Button href={`/profiles/${profile!.id}/edit`} variant="primary" icon={Pencil}>Edit profile</Button>
					{/if}
				{/snippet}
			</EmptyState>
		</Panel>
	{:else}
		<div class="flex flex-col gap-(--gap-panels) lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
			<section class="order-2 flex min-w-0 flex-col gap-(--gap-panels) lg:col-start-1 lg:row-start-1" aria-label="Rules">
				{#if ruleEntries.length > 0 || !fallbackBy}
					<div>
						<h2 class="text-base font-semibold text-ink">Rules</h2>
						<p class="mt-0.5 text-sm text-ink-muted">A piece goes to the first rule that takes it. The numbers are the order.</p>
					</div>

					{#if ruleEntries.length === 0}
						<Panel>
							<EmptyState icon={Funnel} title="No rules yet">
								Every piece goes to {defaultEntry?.bin.name ?? 'Everything else'}.
								{#snippet action()}
									{#if profile!.is_owner}
										<Button href={`/profiles/${profile!.id}/edit`} variant="primary" icon={Pencil}>Edit profile</Button>
									{/if}
								{/snippet}
							</EmptyState>
						</Panel>
					{:else}
						<!-- One card to a line; the owner opens the editor at a bin's rule from it. -->
						<div class="flex flex-col gap-2">
							{#each ruleEntries as entry (entry.id)}
								<div data-bin={entry.id} class="flex min-w-0">
									<ProfileBin
										bin={entry.bin}
										number={entry.number}
										warnings={entry.warnings}
										selected={flashed.has(entry.id)}
										href={profile!.is_owner ? `/profiles/${profile!.id}/edit?rule=${encodeURIComponent(entry.id)}` : undefined}
										class="flex-1"
									/>
								</div>
							{/each}
						</div>
					{/if}
				{/if}

				<Panel title="Fallback" description={fallbackText} flush>
					{#if defaultEntry}
						<div data-bin={defaultEntry.id}>
							<ProfileBin layout="row" bin={defaultEntry.bin} selected={flashed.has(defaultEntry.id)} />
						</div>
					{/if}
					{#if fallbackEntries.length > 0}
						<div class="border-t border-line">
							<div class="flex items-center justify-between gap-3 px-(--pad-panel) py-3">
								<span class="label">
									{fallbackBy === 'color'
										? plural(fallbackEntries.length, 'color')
										: plural(fallbackEntries.length, 'category', 'categories')}
								</span>
								{#if fallbackEntries.length > 10}
									<Input
										type="search"
										size="sm"
										class="w-48"
										bind:value={fallbackFilter}
										placeholder="Filter by name"
										aria-label="Filter by name"
									/>
								{/if}
							</div>
							<ul class="divide-y divide-line border-t border-line">
								{#each fallbackMatches.slice(0, fallbackShown) as entry (entry.id)}
									<li data-bin={entry.id}>
										<ProfileBin layout="row" bin={entry.bin} selected={flashed.has(entry.id)} />
									</li>
								{/each}
							</ul>
							{#if fallbackMatches.length === 0}
								<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">Nothing matches.</p>
							{:else if fallbackMatches.length > fallbackShown}
								<div class="flex items-center gap-3 border-t border-line px-(--pad-panel) py-3">
									<Button size="sm" onclick={() => (fallbackShown += 50)}
										>Show {Math.min(50, fallbackMatches.length - fallbackShown)} more</Button
									>
									<span class="num text-sm text-ink-muted"
										>{(fallbackMatches.length - fallbackShown).toLocaleString('en-US')} not shown</span
									>
								</div>
							{/if}
						</div>
					{/if}
				</Panel>
			</section>

			<div class="contents lg:col-start-2 lg:row-start-1 lg:flex lg:flex-col lg:gap-(--gap-panels)">
				<div class="order-1">
					<RoutePanel profileId={profile.id} versionId={cv.id} {destination} onshow={(id) => void showBin(id)} />
				</div>
				<div class="order-3">
					<VersionList
						{versions}
						shownId={cv.id}
						isOwner={profile.is_owner}
						{publishingId}
						onpick={(v) => void pick(v)}
						onpublish={(v) => void publish(v)}
					/>
				</div>
				{#if hasKits}
					<div class="order-4">
						<KitProgress
							profileId={profile.id}
							bins={Object.fromEntries(entries.map((e) => [e.id, e.bin]))}
						/>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	{#if profile.is_owner}
		<div class="flex max-w-3xl flex-col gap-(--gap-panels)">
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
		</div>
	{/if}
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
