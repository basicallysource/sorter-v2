<script lang="ts">
	import { onMount } from 'svelte';
	import { RefreshCw, ChevronLeft, ChevronRight, Download } from 'lucide-svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import RecordsStats, {
		type Lifetime,
		type Overview,
		type ValueStats
	} from '$lib/components/records/RecordsStats.svelte';
	import RecordsCharts from '$lib/components/records/RecordsCharts.svelte';
	import DailyTable from '$lib/components/records/DailyTable.svelte';
	import PieceCard from '$lib/components/records/PieceCard.svelte';
	import { fetchPieceImageState, type ImageState } from '$lib/components/records/piece-images';
	import { getMachineContext } from '$lib/machines/context';
	import {
		pieceStore,
		pieceToSummary,
		type PieceSummary,
		type PiecesListResponse
	} from '$lib/pieces';

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	const PAGE_SIZE = 100;

	let overview = $state<Overview | null>(null);
	let lifetime = $state<Lifetime | null>(null);
	let value = $state<ValueStats | null>(null);

	let items = $state<PieceSummary[]>([]);
	let total = $state(0);
	let loading = $state(false);
	// Keyset pagination: the cursor used to load page i lives at cursors[i], so
	// prev/next is a plain stack walk — no offset math, no cursor rebasing.
	let cursors = $state<(string | null)[]>([null]);
	let pageIndex = $state(0);
	let nextCursor = $state<string | null>(null);

	let imagesByUuid = $state<Record<string, ImageState>>({});
	let expandedReclassify = $state<Set<string>>(new Set());

	function toggleReclassify(uuid: string) {
		const next = new Set(expandedReclassify);
		if (next.has(uuid)) next.delete(uuid);
		else next.add(uuid);
		expandedReclassify = next;
	}

	let pageNum = $derived(pageIndex + 1);
	let pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
	let rangeStart = $derived(pageIndex * PAGE_SIZE + 1);
	let rangeEnd = $derived(pageIndex * PAGE_SIZE + items.length);

	async function loadOverview() {
		try {
			const res = await fetch(`${effectiveBase()}/api/pieces/overview`);
			if (!res.ok) return;
			overview = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadLifetime() {
		try {
			const res = await fetch(`${effectiveBase()}/api/pieces/lifetime?daily_days=365`);
			if (!res.ok) return;
			lifetime = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadValue() {
		try {
			const res = await fetch(`${effectiveBase()}/api/pieces/value`);
			if (!res.ok) return;
			value = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadPieces() {
		loading = true;
		resetHydration();
		try {
			const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
			const cursor = cursors[pageIndex];
			if (cursor) params.set('cursor', cursor);
			const res = await fetch(`${effectiveBase()}/api/pieces?${params.toString()}`);
			if (!res.ok) return;
			const json = (await res.json()) as PiecesListResponse;
			items = Array.isArray(json?.items) ? json.items : [];
			total = typeof json?.total === 'number' ? json.total : 0;
			nextCursor = json?.next_cursor ?? null;
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	function refresh() {
		cursors = [null];
		pageIndex = 0;
		nextCursor = null;
		void loadOverview();
		void loadLifetime();
		void loadValue();
		void loadPieces();
	}

	function prevPage() {
		if (pageIndex <= 0 || loading) return;
		pageIndex -= 1;
		void loadPieces();
	}

	function nextPage() {
		if (nextCursor === null || loading) return;
		cursors = [...cursors.slice(0, pageIndex + 1), nextCursor];
		pageIndex += 1;
		void loadPieces();
	}

	// --- Live websocket rows ------------------------------------------------
	// known_object events reduce into the shared piece store (fed by
	// MachineManager). On the first page with the default sort, live pieces
	// prepend to the list and listed rows update in place; deeper pages are
	// left undisturbed.
	const machineId = $derived(ctx.machine?.identity?.machine_id ?? null);
	const storeEntries = $derived(pieceStore.entriesFor(machineId));
	const storeByUuid = $derived(new Map(storeEntries.map((p) => [p.uuid, p])));
	const liveWindow = $derived(pageIndex === 0);

	function isResolvedStatus(status: string | null | undefined): boolean {
		return (
			status === 'classified' ||
			status === 'failed' ||
			status === 'unknown' ||
			status === 'not_found' ||
			status === 'multi_drop_fail'
		);
	}

	type DisplayRow = { piece: PieceSummary; live: boolean; liveCrop: string | null };

	const displayRows = $derived.by<DisplayRow[]>(() => {
		const rows: DisplayRow[] = [];
		if (liveWindow) {
			const page_uuids = new Set(items.map((i) => i.uuid));
			const top_seen = items[0]?.seen_at ?? 0;
			const live = storeEntries
				.filter((p) => p.ws != null && p.ws.first_carousel_seen_ts != null)
				.filter((p) => !page_uuids.has(p.uuid))
				.filter((p) => (p.seen_at ?? 0) > top_seen)
				.sort((a, b) => (b.seen_at ?? 0) - (a.seen_at ?? 0));
			for (const p of live) {
				rows.push({
					piece: pieceToSummary(p),
					live: true,
					liveCrop: p.ws?.latest_captured_crop
						? `data:image/jpeg;base64,${p.ws.latest_captured_crop}`
						: null
				});
			}
		}
		for (const item of items) {
			const s = storeByUuid.get(item.uuid);
			rows.push({
				piece: s?.ws ? pieceToSummary(s) : item,
				live: false,
				liveCrop: null
			});
		}
		return rows;
	});

	const liveCount = $derived(displayRows.reduce((n, r) => n + (r.live ? 1 : 0), 0));

	// --- Image hydration ------------------------------------------------------
	// Crops load a few at a time instead of firing 100 concurrent requests at
	// the backend. A generation counter cancels in-flight work when the page
	// changes. Live rows only hydrate once their classification resolves — until
	// then the card shows the latest socket crop.
	const HYDRATE_CONCURRENCY = 6;
	let hydrateGeneration = 0;
	let hydrate_queue: { uuid: string; seen_at: number | null }[] = [];
	let active_workers = 0;
	let queued_uuids = new Set<string>();

	function resetHydration() {
		hydrateGeneration += 1;
		hydrate_queue = [];
		queued_uuids = new Set();
		imagesByUuid = {};
	}

	async function runHydrateWorker(generation: number): Promise<void> {
		active_workers += 1;
		try {
			while (hydrate_queue.length > 0 && generation === hydrateGeneration) {
				const next = hydrate_queue.shift();
				if (!next) return;
				if (imagesByUuid[next.uuid]?.status === 'ok') continue;
				imagesByUuid = { ...imagesByUuid, [next.uuid]: { status: 'loading', images: [] } };
				const result = await fetchPieceImageState(effectiveBase(), next.uuid, next.seen_at);
				if (generation !== hydrateGeneration) return;
				imagesByUuid = { ...imagesByUuid, [next.uuid]: result };
			}
		} finally {
			active_workers -= 1;
		}
	}

	function enqueueHydration(candidates: { uuid: string; seen_at: number | null }[]): void {
		for (const c of candidates) {
			queued_uuids.add(c.uuid);
			hydrate_queue.push(c);
		}
		const generation = hydrateGeneration;
		while (active_workers < HYDRATE_CONCURRENCY && hydrate_queue.length > active_workers) {
			void runHydrateWorker(generation);
		}
	}

	$effect(() => {
		const candidates: { uuid: string; seen_at: number | null }[] = [];
		for (const row of displayRows) {
			if (queued_uuids.has(row.piece.uuid)) continue;
			if (row.live && !isResolvedStatus(row.piece.classification_status) && !row.piece.dead)
				continue;
			candidates.push({ uuid: row.piece.uuid, seen_at: row.piece.seen_at ?? null });
		}
		if (candidates.length > 0) enqueueHydration(candidates);
	});

	onMount(() => {
		refresh();
	});
</script>

<svelte:head>
	<title>Records · Sorter</title>
</svelte:head>

{#snippet pager()}
	<div class="flex items-center gap-3 text-sm text-text-muted">
		<span>
			{#if total > 0}
				{rangeStart.toLocaleString()}–{rangeEnd.toLocaleString()} of {total.toLocaleString()}
				{#if liveCount > 0}
					<span class="text-primary">+{liveCount} live</span>
				{/if}
			{:else}
				0 records
			{/if}
		</span>
		<div class="flex border border-border">
			<button
				type="button"
				onclick={prevPage}
				disabled={pageIndex <= 0 || loading}
				aria-label="Previous page"
				class="border-r border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
			>
				<ChevronLeft size={14} />
			</button>
			<span class="px-3 py-1 text-text">{pageNum} / {pageCount}</span>
			<button
				type="button"
				onclick={nextPage}
				disabled={nextCursor === null || loading}
				aria-label="Next page"
				class="border-l border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
			>
				<ChevronRight size={14} />
			</button>
		</div>
	</div>
{/snippet}

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-4 p-4 sm:p-6">
		<header class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
			<div>
				<h2 class="text-xl font-bold text-text">Records</h2>
				<p class="mt-1 text-sm text-text-muted">
					Sorting history for this machine — every piece seen across all saved runs.
				</p>
			</div>
			<button
				type="button"
				onclick={refresh}
				disabled={loading}
				aria-label="Reload"
				title="Reload records"
				class="border border-border bg-surface p-1.5 text-text-muted hover:text-text disabled:opacity-50"
			>
				<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			</button>
		</header>

		<RecordsStats {overview} {lifetime} {value} />

		<RecordsCharts endpointBase={effectiveBase()} />

		<DailyTable
			daily={lifetime?.daily ?? []}
			exportUrl={`${effectiveBase()}/api/pieces/lifetime/export.csv`}
		/>

		<div class="flex items-center justify-between gap-3">
			<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">Pieces</h3>
			<div class="flex items-center gap-3">
				<a
					href={`${effectiveBase()}/api/pieces/export.csv`}
					download
					class="inline-flex items-center justify-center gap-2 border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text transition-colors hover:bg-bg"
					title="Download every recorded piece as CSV (streamed from the backend)"
				>
					<Download size={13} />
					Export CSV
				</a>
				{@render pager()}
			</div>
		</div>

		{#if displayRows.length === 0}
			<div class="border border-border bg-surface p-8 text-center text-sm text-text-muted">
				{loading ? 'Loading…' : 'No records yet.'}
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				{#each displayRows as row (row.piece.uuid)}
					<PieceCard
						piece={row.piece}
						imgState={imagesByUuid[row.piece.uuid]}
						endpointBase={effectiveBase()}
						liveCrop={row.liveCrop}
						reclassifyOpen={expandedReclassify.has(row.piece.uuid)}
						onToggleReclassify={() => toggleReclassify(row.piece.uuid)}
					/>
				{/each}
			</div>

			<div class="flex items-center justify-end gap-3">
				{@render pager()}
			</div>
		{/if}
	</div>
</div>
