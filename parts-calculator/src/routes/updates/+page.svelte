<script lang="ts">
	import { ArrowLeft, CalendarClock, Download, FlaskConical, History, Info, Plus, RefreshCw } from 'lucide-svelte';
	import Badge from '$lib/components/Badge.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import PartDetailModal from '$lib/components/PartDetailModal.svelte';
	import Seo from '$lib/components/Seo.svelte';
	import {
		commitUrl,
		duration,
		fmtDate,
		grams,
		machineQty,
		partDownload,
		type Part,
		type PartVersion
	} from '$lib/filament';
	import { layerStore } from '$lib/layers.svelte';
	import {
		candidatesSince,
		catalogStart,
		daysAgo,
		partUpdatesSince,
		type PartUpdate
	} from '$lib/updates';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';

	// A time-based diff of the catalog: given a date, what has changed between
	// then and now. It tracks the catalog, not the reader — nothing here knows
	// or records what anybody has printed, and the date is just one end of the
	// comparison. The dates are already in the data (`created_at`, `updated_at`
	// and a dated `versions` entry per revision), so this page is a filter over
	// them, not a second record of what changed.
	const START = catalogStart();
	const KEY = 'sorter-updates-since-v1';

	const isDate = (v: string | null | undefined): v is string => !!v && /^\d{4}-\d{2}-\d{2}$/.test(v);

	// The page is prerendered, so the date can only be read once we are in the
	// browser: `?since=` first (a shared link wins), then the last date this
	// person used, then a month back as a starting point.
	let since = $state('');

	onMount(() => {
		const fromUrl = page.url.searchParams.get('since');
		let stored: string | null = null;
		try {
			stored = localStorage.getItem(KEY);
		} catch {
			/* storage disabled */
		}
		since = [fromUrl, stored, daysAgo(30)].find(isDate) ?? '';
	});

	// Only a deliberate choice writes back — the URL and storage are updated in
	// the handler rather than from an effect, so nothing calls replaceState
	// while the router is still hydrating (which throws, and takes the page
	// with it).
	function pick(value: string) {
		since = value;
		if (!browser) return;
		try {
			localStorage.setItem(KEY, value);
		} catch {
			/* storage full / disabled */
		}
		const params = new URLSearchParams(location.search);
		if (isDate(value)) params.set('since', value);
		else params.delete('since');
		const qs = params.toString();
		const target = qs ? `${location.pathname}?${qs}` : location.pathname;
		if (target !== location.pathname + location.search) replaceState(target, {});
	}

	const layers = $derived(layerStore.sizes.length);
	const updates = $derived(partUpdatesSince(since));
	const added = $derived(updates.filter((u) => u.kind === 'new'));
	const revised = $derived(updates.filter((u) => u.kind === 'revised'));
	const touched = $derived(updates.filter((u) => u.kind === 'touched'));
	const candidates = $derived(candidatesSince(since));

	// What the difference weighs: every new part plus one of every revised one,
	// at the current layer count. A size for the diff, not an instruction.
	const changed = $derived([...added, ...revised]);
	const changedGrams = $derived(
		changed.reduce((sum, u) => sum + u.part.grams * machineQty(u.part, layers), 0)
	);
	const changedSeconds = $derived(
		changed.reduce((sum, u) => sum + u.part.print_seconds * machineQty(u.part, layers), 0)
	);

	const presets = [
		{ label: 'Last 7 days', value: () => daysAgo(7) },
		{ label: 'Last 30 days', value: () => daysAgo(30) },
		{ label: 'Last 90 days', value: () => daysAgo(90) },
		{ label: 'Everything', value: () => START }
	];

	let modelOpen = $state(false);
	let modelPart = $state<Part | null>(null);
	let modelColor = $state('ash-gray');
	let modelVersion = $state<PartVersion | null>(null);
	function openModel(part: Part, version: PartVersion | null = null) {
		modelPart = part;
		modelVersion = version ?? part.versions?.[part.versions.length - 1] ?? null;
		modelOpen = true;
	}
</script>

{#snippet partRow(u: PartUpdate)}
	{@const qty = machineQty(u.part, layers)}
	<li class="flex gap-3 border-b border-border px-3 py-3 last:border-b-0">
		<button
			type="button"
			class="group shrink-0 cursor-pointer"
			title="Open the current 3D model for {u.part.name}"
			onclick={() => openModel(u.part)}
		>
			<span class="flex h-16 w-20 items-center justify-center overflow-hidden border border-border bg-[var(--color-bg)] group-hover:border-primary">
				<img src={u.part.render} alt={u.part.name} class="h-full w-full object-contain transition-transform group-hover:scale-105" />
			</span>
		</button>

		<div class="min-w-0 flex-1">
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
				<a href="/part/{u.part.id}" class="font-bold leading-tight text-text hover:text-primary">{u.part.name}</a>
				{#if u.kind === 'new'}
					<Badge variant="success"><Plus size={11} /> New</Badge>
				{:else if u.kind === 'revised'}
					<Badge variant="warning"><RefreshCw size={11} /> Revised · v{u.part.version}</Badge>
				{:else}
					<Badge variant="neutral"><Info size={11} /> Listing only</Badge>
				{/if}
				<span class="text-xs text-text-muted">{fmtDate(u.date)}</span>
				{#if qty}<span class="text-xs text-text-muted">· {qty}× per machine</span>{/if}
				<ChangeStatus kind="parts" id={u.part.id} name={u.part.name} />
			</div>

			{#if u.kind === 'revised'}
				<ul class="mt-1.5 space-y-1.5">
					{#each [...u.newVersions].reverse() as v (v.version)}
						<li class="text-xs leading-relaxed text-text-muted">
							<span class="font-semibold text-text">v{v.version}</span>
							<span>· {fmtDate(v.date)}</span>
							{#if commitUrl(v.commit)}
								<a href={commitUrl(v.commit)} target="_blank" rel="noopener" class="text-primary hover:text-primary-hover">{v.commit}</a>
							{/if}
							<span class="block">{v.message}</span>
						</li>
					{/each}
				</ul>
				{#if u.atCutoff}
					<p class="mt-1.5 text-xs text-text-muted">
						Current on that date: <b class="text-text">v{u.atCutoff.version}</b> ({fmtDate(u.atCutoff.date)}).
						{#if u.atCutoff.stl}
							<a href={u.atCutoff.stl} download class="text-primary hover:text-primary-hover">Download that older STL</a> to compare.
						{/if}
					</p>
				{/if}
			{:else}
				<p class="mt-1 text-xs leading-relaxed text-text-muted">{u.part.description}</p>
			{/if}
		</div>

		<div class="flex shrink-0 flex-col items-end gap-1.5">
			{#if u.kind !== 'touched'}
				<a
					href={partDownload(u.part, false)}
					download
					class="setup-button-secondary inline-flex h-8 items-center gap-1.5 px-3 text-xs font-semibold"
					title="Download the current {u.part.name}.stl"
				>
					<Download size={14} /> STL
				</a>
				<span class="text-[11px] text-text-muted">{grams(u.part.grams * Math.max(qty, 1))} · {duration(u.part.print_seconds * Math.max(qty, 1))}</span>
			{:else}
				<a href="/part/{u.part.id}" class="text-xs text-primary hover:text-primary-hover">Open part</a>
			{/if}
		</div>
	</li>
{/snippet}

{#snippet section(title: string, blurb: string, rows: PartUpdate[], icon: 'new' | 'revised' | 'touched')}
	{#if rows.length}
		<section class="mb-8">
			<h2 class="flex items-center gap-2 text-xl font-bold tracking-tight text-text">
				{#if icon === 'new'}<Plus size={18} class="text-success" />{:else if icon === 'revised'}<RefreshCw size={18} class="text-warning-dark" />{:else}<Info size={18} class="text-text-muted" />{/if}
				{title} <span class="text-text-muted">({rows.length})</span>
			</h2>
			<p class="mb-3 mt-1 max-w-3xl text-sm text-text-muted">{blurb}</p>
			<ul class="border border-border bg-surface">
				{#each rows as u (u.part.id)}{@render partRow(u)}{/each}
			</ul>
		</section>
	{/if}
{/snippet}

<Seo
	title="What changed since"
	description="A time-based diff of the Sorter V2 printed-parts catalog: pick a date and see which parts are new since, which have a newer design revision, and which listings changed."
/>

<main class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<a href="/" class="mb-5 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:text-primary-hover"><ArrowLeft size={15} /> Printed parts</a>

	<div class="mb-6">
		<h1 class="text-3xl font-bold tracking-tight text-text">What changed since…</h1>
		<p class="mt-2 max-w-3xl text-sm text-text-muted">
			A time-based diff of the catalog. Pick any date and this lists what has moved between then and
			now: parts that did not exist yet, parts that have a newer design revision, and entries whose
			listing changed without the geometry moving. It reads the dates already in the catalog, so
			there is no second changelog to maintain and nothing here records what you have printed.
		</p>
	</div>

	<div class="setup-panel mb-6 flex flex-wrap items-end gap-x-4 gap-y-3 p-4">
		<label class="flex flex-col gap-1 text-sm">
			<span class="font-semibold text-text">Changes since</span>
			<span class="inline-flex items-center gap-2">
				<CalendarClock size={16} class="text-text-muted" />
				<input
					type="date"
					value={since}
					min={START}
					onchange={(e) => pick(e.currentTarget.value)}
					class="border border-border bg-[var(--color-bg)] px-2 py-1.5 text-sm text-text"
				/>
			</span>
		</label>
		<div class="flex flex-wrap items-center gap-2">
			{#each presets as preset (preset.label)}
				<button
					type="button"
					class="border border-border px-2.5 py-1.5 text-xs font-semibold text-text-muted transition-colors hover:border-primary hover:text-primary"
					onclick={() => pick(preset.value())}
				>
					{preset.label}
				</button>
			{/each}
		</div>
	</div>

	{#if !since}
		<p class="border border-border bg-surface px-4 py-6 text-sm text-text-muted">Pick a date to see what has changed since then.</p>
	{:else}
		<p class="mb-6 border border-border bg-surface px-4 py-3 text-sm text-text">
			Since <b>{fmtDate(since)}</b>:
			<b>{added.length}</b> new {added.length === 1 ? 'part' : 'parts'},
			<b>{revised.length}</b> revised,
			<b>{touched.length}</b> listing-only {touched.length === 1 ? 'change' : 'changes'}.
			{#if changed.length}
				<span class="mt-1 block text-text-muted">
					The new and revised parts together, at {layers} layer{layers === 1 ? '' : 's'}:
					<b class="text-text">{grams(changedGrams)}</b> of filament, about
					<b class="text-text">{duration(changedSeconds)}</b> of printer time.
				</span>
			{/if}
		</p>

		{@render section(
			'New parts',
			'These did not exist in the catalog on that date.',
			added,
			'new'
		)}
		{@render section(
			'Revised parts',
			'A design revision was released after that date. The version notes below say what changed and why, and the older revision is linked so the two can be compared.',
			revised,
			'revised'
		)}
		{@render section(
			'Listing changed, design did not',
			'Same design revision as on that date — only the catalog entry moved (description, quantity, colour or pictures). The geometry is identical.',
			touched,
			'touched'
		)}

		{#if candidates.length}
			<section class="mb-8">
				<h2 class="flex items-center gap-2 text-xl font-bold tracking-tight text-text">
					<FlaskConical size={18} class="text-info" /> Revisions under test <span class="text-text-muted">({candidates.length})</span>
				</h2>
				<p class="mb-3 mt-1 max-w-3xl text-sm text-text-muted">
					Candidates raised since that date: alternative designs being tested for a part's slot. They
					are not part of the build and carry no version number, but they are a change to the
					catalog like any other.
				</p>
				<ul class="border border-border bg-surface">
					{#each candidates as c (c.candidate.uid)}
						<li class="flex gap-3 border-b border-border px-3 py-3 last:border-b-0">
							{#if c.candidate.render}
								<span class="flex h-16 w-20 shrink-0 items-center justify-center overflow-hidden border border-border bg-[var(--color-bg)]">
									<img src={c.candidate.render} alt={c.candidate.name ?? c.part.name} class="h-full w-full object-contain" />
								</span>
							{/if}
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
									<a href="/part/{c.part.id}" class="font-bold leading-tight text-text hover:text-primary">{c.candidate.name ?? c.part.name}</a>
									<Badge variant="info"><FlaskConical size={11} /> Candidate {c.candidate.uid.toUpperCase()}</Badge>
									<span class="text-xs text-text-muted">{fmtDate(c.candidate.created_at)}</span>
									{#if c.candidate.superseded_by}<Badge variant="neutral"><History size={11} /> Superseded</Badge>{/if}
								</div>
								<p class="mt-1 text-xs leading-relaxed text-text-muted">{c.candidate.message}</p>
							</div>
							<div class="shrink-0">
								<a href={c.candidate.stl} download class="setup-button-secondary inline-flex h-8 items-center gap-1.5 px-3 text-xs font-semibold" title="Download the candidate STL"><Download size={14} /> STL</a>
							</div>
						</li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if !updates.length && !candidates.length}
			<p class="border border-border bg-surface px-4 py-6 text-sm text-text-muted">
				Nothing in the catalog has changed since {fmtDate(since)}.
			</p>
		{/if}
	{/if}
</main>

<PartDetailModal bind:open={modelOpen} part={modelPart} bind:colorId={modelColor} bind:version={modelVersion} />
