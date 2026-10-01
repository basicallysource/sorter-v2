<script lang="ts">
	import { onMount } from 'svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Download from '@lucide/svelte/icons/download';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import RecordsStats, {
		type Lifetime,
		type Overview,
		type ValueStats
	} from '$lib/components/records/RecordsStats.svelte';
	import RecordsCharts from '$lib/components/records/RecordsCharts.svelte';
	import IncidentsReport from '$lib/components/records/IncidentsReport.svelte';
	import DailyTable from '$lib/components/records/DailyTable.svelte';
	import PieceCard from '$lib/components/records/PieceCard.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
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

	// A correction returns the fresh summary. Update the rest-loaded page list in
	// place and feed the store so live rows (and RecentObjects) reflect it too.
	function onPieceCorrected(summary: PieceSummary) {
		items = items.map((it) => (it.uuid === summary.uuid ? { ...it, ...summary } : it));
		const mid = ctx.machine?.identity?.machine_id ?? null;
		if (mid) pieceStore.upsertFromRest(mid, [summary]);
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
			// A live-seen piece keeps its store view (fresh crop/status), but the
			// correction state is DB-authoritative — take it from the REST item so a
			// live WS event (which carries no verdict) can't blank it out.
			rows.push({
				piece: s?.ws
					? {
							...pieceToSummary(s),
							correctable: item.correctable,
							part_correct: item.part_correct,
							color_corrected_id: item.color_corrected_id,
							part_feedback_submitted: item.part_feedback_submitted,
							color_feedback_submitted: item.color_feedback_submitted
						}
					: item,
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
	<title>Records - Sorter</title>
</svelte:head>

{#snippet pager()}
	<div class="flex items-center gap-3 text-sm text-ink-muted">
		<span class="num">
			{#if total > 0}
				{rangeStart.toLocaleString()}–{rangeEnd.toLocaleString()} of {total.toLocaleString()}
				{#if liveCount > 0}<span class="text-primary-ink">+{liveCount} live</span>{/if}
			{:else}
				0 records
			{/if}
		</span>
		<div class="flex items-center gap-1">
			<Button
				size="sm"
				variant="ghost"
				icon={ChevronLeft}
				label="Previous page"
				disabled={pageIndex <= 0 || loading}
				onclick={prevPage}
			/>
			<span class="num px-1 text-ink">{pageNum} / {pageCount}</span>
			<Button
				size="sm"
				variant="ghost"
				icon={ChevronRight}
				label="Next page"
				disabled={nextCursor === null || loading}
				onclick={nextPage}
			/>
		</div>
	</div>
{/snippet}

<AppShell>
	<div class="mx-auto flex w-full max-w-[1500px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader
			title="Records"
			description="Sorting history for this machine: every piece seen across all saved runs."
		>
			{#snippet actions()}
				<Button icon={RefreshCw} label="Reload the records" {loading} onclick={refresh} />
			{/snippet}
		</PageHeader>

		<RecordsStats {overview} {lifetime} {value} />

		<RecordsCharts endpointBase={effectiveBase()} />

		<IncidentsReport endpointBase={effectiveBase()} />

		<DailyTable
			daily={lifetime?.daily ?? []}
			exportUrl={`${effectiveBase()}/api/pieces/lifetime/export.csv`}
		/>

		<section class="flex flex-col gap-3">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<h2 class="text-base font-semibold text-ink">Pieces</h2>
				<div class="flex flex-wrap items-center gap-3">
					<Button size="sm" icon={Download} href={`${effectiveBase()}/api/pieces/export.csv`} download>
						Export CSV
					</Button>
					{@render pager()}
				</div>
			</div>

			{#if displayRows.length === 0}
				<EmptyState title={loading ? 'Loading the records' : 'No records yet'} />
			{:else}
				<div class="flex flex-col gap-(--gap-panels)">
					{#each displayRows as row (row.piece.uuid)}
						<PieceCard
							piece={row.piece}
							imgState={imagesByUuid[row.piece.uuid]}
							endpointBase={effectiveBase()}
							liveCrop={row.liveCrop}
							reclassifyOpen={expandedReclassify.has(row.piece.uuid)}
							onToggleReclassify={() => toggleReclassify(row.piece.uuid)}
							{onPieceCorrected}
						/>
					{/each}
				</div>

				<div class="flex justify-end">{@render pager()}</div>
			{/if}
		</section>
	</div>
</AppShell>
