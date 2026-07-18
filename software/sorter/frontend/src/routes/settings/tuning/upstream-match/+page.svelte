<script lang="ts">
	import { page } from '$app/state';
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import TuningParamRow from '$lib/components/settings/TuningParamRow.svelte';
	import {
		groupTuningSections,
		type TuningFieldMeta,
		type TuningValues
	} from '$lib/settings/tuning';
	import UpstreamMatchSearch from '$lib/components/UpstreamMatchSearch.svelte';
	import UpstreamWindowTimeline from '$lib/components/UpstreamWindowTimeline.svelte';

	const initialUuid = page.url.searchParams.get('uuid') ?? '';

	let fields = $state<TuningFieldMeta[]>([]);
	let values = $state<TuningValues>({});
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);
	let stats = $state<any>(null);
	let searchReload = $state(0);

	let sections = $derived(groupTuningSections(fields));

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/upstream-match`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			fields = data.fields;
			values = { ...data.config };
			stats = data.stats;
		} catch (e: any) {
			error = e.message ?? 'Failed to load config';
		} finally {
			loading = false;
		}
	}

	async function save() {
		saving = true;
		saved = false;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/upstream-match`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(values)
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			values = { ...data.config };
			saved = true;
			searchReload += 1; // make the search component pick up the new defaults
			setTimeout(() => (saved = false), 3000);
		} catch (e: any) {
			error = e.message ?? 'Failed to save config';
		} finally {
			saving = false;
		}
	}

	function channelLabel(ch: number): string {
		return ch === 2 ? 'C2' : ch === 3 ? 'C3' : `C${ch}`;
	}

	// --- embedded-crops gallery ---
	type Crop = { channel_id: number; ts: number; bbox: number[]; jpeg_b64: string };
	let cropItems = $state<Crop[]>([]);
	let cropTotal = $state(0);
	let cropOffset = $state(0);
	const cropLimit = 60;
	let cropChannel = $state<number | null>(null);
	let cropsLoading = $state(false);
	let cropsError = $state<string | null>(null);

	async function loadCrops() {
		cropsLoading = true;
		cropsError = null;
		try {
			const qs = new URLSearchParams({ offset: String(cropOffset), limit: String(cropLimit) });
			if (cropChannel != null) qs.set('channel', String(cropChannel));
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/upstream-match/crops?${qs}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			cropItems = data.items ?? [];
			cropTotal = data.total ?? 0;
			if (data.error) cropsError = data.error;
		} catch (e: any) {
			cropsError = e.message ?? 'Failed to load crops';
			cropItems = [];
		} finally {
			cropsLoading = false;
		}
	}

	function cropPage(delta: number) {
		const next = cropOffset + delta * cropLimit;
		if (next < 0 || next >= cropTotal) return;
		cropOffset = next;
		loadCrops();
	}

	function setCropChannel(ch: number | null) {
		cropChannel = ch;
		cropOffset = 0;
		loadCrops();
	}

	function ageStr(ts: number): string {
		const a = Date.now() / 1000 - ts;
		if (a < 60) return `${a.toFixed(0)}s ago`;
		if (a < 3600) return `${(a / 60).toFixed(1)}m ago`;
		return `${(a / 3600).toFixed(1)}h ago`;
	}

	function fmtCount(s: any): string {
		if (!s) return '—';
		const state = s.sorting ? 'COLLECTING (machine running)' : 'idle (only collects while sorting)';
		const chans = s.channels
			? Object.entries(s.channels)
					.map(([ch, v]: any) => `C${ch}: ${v.count}`)
					.join('  ·  ')
			: 'no crops yet';
		const extra = [`embedded ${s.embedded_total ?? 0}`, `queued ${s.queued ?? 0}`];
		if (s.dropped_total) extra.push(`dropped ${s.dropped_total}`);
		if (s.last_embed_error) extra.push(`err: ${s.last_embed_error}`);
		return `${state}  —  ${chans}  —  ${extra.join('  ·  ')}`;
	}

	let didInit = $state(false);
	$effect(() => {
		if (didInit) return;
		didInit = true;
		load();
		loadCrops();
	});
</script>

<svelte:head><title>Sorter - Upstream Match Tuning</title></svelte:head>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Upstream Match (experimental)</div>
		<div class="mt-1 text-sm text-text-muted">
			Pulls crops of a classified piece from the channels it passed through (C2/C3), ranked by
			image-embedding similarity. Collection only runs while the machine is sorting.
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}
	{#if saved}
		<Alert variant="success">Saved. Collection updated within ~1 second.</Alert>
	{/if}

	<SectionCard title="Search" description="Look up upstream crops for a specific piece by UUID.">
		<UpstreamMatchSearch
			{initialUuid}
			autoShowAll={initialUuid !== ''}
			reloadToken={searchReload}
		/>
		<div class="mt-4 text-sm text-text-muted">Store: {fmtCount(stats)}</div>
	</SectionCard>

	<SectionCard
		title="Embedded crops (in vector DB)"
		description="What's actually been embedded and stored — newest first. Only fills while the machine is RUNNING."
	>
		<div class="flex flex-col gap-3">
			<div class="flex flex-wrap items-center gap-2">
				<span class="text-sm text-text-muted">Channel:</span>
				<Button
					variant={cropChannel === null ? 'primary' : 'secondary'}
					size="sm"
					onclick={() => setCropChannel(null)}>All</Button
				>
				<Button
					variant={cropChannel === 2 ? 'primary' : 'secondary'}
					size="sm"
					onclick={() => setCropChannel(2)}>C2</Button
				>
				<Button
					variant={cropChannel === 3 ? 'primary' : 'secondary'}
					size="sm"
					onclick={() => setCropChannel(3)}>C3</Button
				>
				<div class="flex-1"></div>
				<Button variant="secondary" size="sm" onclick={loadCrops} loading={cropsLoading}
					>Refresh</Button
				>
			</div>

			<div class="flex items-center gap-3 text-sm text-text-muted">
				<Button
					variant="secondary"
					size="sm"
					onclick={() => cropPage(-1)}
					disabled={cropOffset === 0}>‹ Prev</Button
				>
				<span>
					{cropTotal === 0
						? '0'
						: `${cropOffset + 1}–${Math.min(cropOffset + cropLimit, cropTotal)}`} of {cropTotal}
				</span>
				<Button
					variant="secondary"
					size="sm"
					onclick={() => cropPage(1)}
					disabled={cropOffset + cropLimit >= cropTotal}>Next ›</Button
				>
			</div>

			{#if cropsError}
				<Alert variant="warning">{cropsError}</Alert>
			{/if}

			{#if cropsLoading}
				<div class="text-sm text-text-muted">Loading…</div>
			{:else if cropItems.length === 0}
				<div class="text-sm text-text-muted">
					Nothing embedded yet. Crops are only collected while the machine is actively sorting.
				</div>
			{:else}
				<div
					class="grid gap-2"
					style="grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));"
				>
					{#each cropItems as crop (crop.channel_id + '-' + crop.ts + '-' + crop.bbox.join(','))}
						<div class="flex flex-col border border-border bg-bg">
							<div class="aspect-square w-full bg-white">
								<img
									src={`data:image/jpeg;base64,${crop.jpeg_b64}`}
									alt="crop"
									class="h-full w-full object-contain"
									loading="lazy"
								/>
							</div>
							<div class="flex items-center justify-between px-2 py-1.5 text-sm text-text-muted">
								<span>{channelLabel(crop.channel_id)}</span>
								<span>{ageStr(crop.ts)}</span>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</SectionCard>

	<SectionCard title="Parameters" description="Collection, embedding, and search tuning.">
		{#if loading}
			<div class="text-sm text-text-muted">Loading…</div>
		{:else}
			<div class="flex flex-col gap-8">
				{#each sections as section}
					<div class="flex flex-col gap-2">
						<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
							{section.name}
						</div>
						{#if section.name === 'Search' && 'ch2_window_start_s' in values}
							<UpstreamWindowTimeline bind:values />
						{/if}
						{#each section.fields as field}
							<TuningParamRow {field} bind:values />
						{/each}
					</div>
				{/each}
			</div>

			<div class="mt-6 flex gap-3">
				<Button variant="primary" onclick={save} loading={saving}>Save defaults</Button>
				<Button variant="secondary" onclick={load} disabled={saving}>Reset to saved</Button>
			</div>
			<div class="mt-2 text-sm text-text-muted">
				Save persists these as the defaults the search uses (and across restarts).
			</div>
		{/if}
	</SectionCard>
</div>
