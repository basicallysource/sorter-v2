<script lang="ts">
	import { onMount } from 'svelte';
	import { RefreshCw, ChevronLeft, ChevronRight, ExternalLink, FlaskConical } from 'lucide-svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import ImageInfoBadge from '$lib/components/ImageInfoBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
	import type {
		ClassificationAttempt,
		ClassificationAttemptStrategy,
		KnownObjectData,
		RecognitionImage
	} from '$lib/api/events';

	type ImageState = {
		status: 'loading' | 'ok' | 'missing';
		images: RecognitionImage[];
		strategy?: ClassificationAttemptStrategy | null;
		attempts?: ClassificationAttempt[];
	};

	type Overview = {
		total_runs: number;
		total_pieces: number;
		classified_pieces: number;
		distributed_pieces: number;
		unique_parts: number;
		unique_colors: number;
		first_seen: number | null;
		last_seen: number | null;
	};

	type PieceItem = {
		uuid: string;
		run_id: string;
		seen_at: number | null;
		classification_status: string | null;
		part_id: string | null;
		part_name: string | null;
		color_id: string | null;
		color_name: string | null;
		category_id: string | null;
		confidence: number | null;
		destination_bin: number[] | null;
	};

	type LifetimeDay = {
		day: string;
		seconds_powered: number;
		seconds_sorted: number;
		pieces_seen: number;
		pieces_classified: number;
		pieces_distributed: number;
	};

	type Lifetime = {
		seconds_sorted: number;
		seconds_powered: number;
		pieces_seen: number;
		pieces_classified: number;
		pieces_distributed: number;
		overall_ppm: number;
		best_hour_ppm: number;
		active_days: number;
		first_hour: number | null;
		last_hour: number | null;
		daily: LifetimeDay[];
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	const PAGE_SIZE = 100;

	let overview = $state<Overview | null>(null);
	let lifetime = $state<Lifetime | null>(null);
	let pieces = $state<PieceItem[]>([]);
	let total = $state(0);
	let offset = $state(0);
	let loading = $state(false);
	let imagesByUuid = $state<Record<string, ImageState>>({});
	let expandedReclassify = $state<Set<string>>(new Set());

	function toggleReclassify(uuid: string) {
		const next = new Set(expandedReclassify);
		if (next.has(uuid)) next.delete(uuid);
		else next.add(uuid);
		expandedReclassify = next;
	}

	let pageNum = $derived(Math.floor(offset / PAGE_SIZE) + 1);
	let pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));

	async function loadOverview() {
		try {
			const res = await fetch(`${effectiveBase()}/api/records/overview`);
			if (!res.ok) return;
			overview = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadLifetime() {
		try {
			const res = await fetch(`${effectiveBase()}/api/records/lifetime`);
			if (!res.ok) return;
			lifetime = await res.json();
		} catch {
			// ignore
		}
	}

	async function loadPieces() {
		loading = true;
		try {
			const res = await fetch(
				`${effectiveBase()}/api/records/pieces?offset=${offset}&limit=${PAGE_SIZE}`
			);
			if (!res.ok) return;
			const json = await res.json();
			pieces = Array.isArray(json?.pieces) ? json.pieces : [];
			total = typeof json?.total === 'number' ? json.total : 0;
			for (const p of pieces) void fetchImages(p.uuid);
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	// The paginated record carries only classification results; its recognition
	// crops (C4 burst + upstream C2/C3 matches) live in the in-memory lookup and
	// are fetched per-uuid. Pieces aged out of that lookup return 404 → 'missing'.
	async function fetchImages(uuid: string) {
		if (imagesByUuid[uuid]?.status === 'ok') return;
		imagesByUuid = { ...imagesByUuid, [uuid]: { status: 'loading', images: [] } };
		try {
			const res = await fetch(`${effectiveBase()}/api/known-objects/${encodeURIComponent(uuid)}`);
			if (!res.ok) {
				imagesByUuid = { ...imagesByUuid, [uuid]: { status: 'missing', images: [] } };
				return;
			}
			const data = (await res.json()) as KnownObjectData;
			imagesByUuid = {
				...imagesByUuid,
				[uuid]: {
					status: 'ok',
					images: data.recognition_image_set ?? [],
					strategy: data.classification_strategy ?? null,
					attempts: data.classification_attempts ?? []
				}
			};
		} catch {
			imagesByUuid = { ...imagesByUuid, [uuid]: { status: 'missing', images: [] } };
		}
	}

	function refresh() {
		void loadOverview();
		void loadLifetime();
		void loadPieces();
	}

	function prevPage() {
		if (offset <= 0) return;
		offset = Math.max(0, offset - PAGE_SIZE);
		imagesByUuid = {};
		void loadPieces();
	}

	function nextPage() {
		if (offset + PAGE_SIZE >= total) return;
		offset = offset + PAGE_SIZE;
		imagesByUuid = {};
		void loadPieces();
	}

	function formatTimestamp(ts: number | null): string {
		if (ts == null) return '—';
		const d = new Date(ts * 1000);
		return d.toLocaleString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatDate(ts: number | null): string {
		if (ts == null) return '—';
		return new Date(ts * 1000).toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	}

	function formatStatus(status: string | null): string {
		if (!status) return 'unknown';
		return status.replace(/_/g, ' ');
	}

	function formatBin(bin: number[] | null): string {
		if (!bin || bin.length === 0) return '—';
		return bin.join(', ');
	}

	function formatConfidence(c: number | null): string {
		if (c == null) return '—';
		return `${(c * 100).toFixed(0)}%`;
	}

	function confidenceClass(conf: number | null): string {
		if (conf == null) return 'text-text-muted';
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	function statusChipClass(status: string | null): string {
		if (status === 'classified') return 'border-success bg-success/10 text-success';
		if (status === 'unknown' || status === 'not_found')
			return 'border-text-muted bg-text-muted/10 text-text-muted';
		if (status === 'multi_drop_fail') return 'border-danger bg-danger/10 text-danger';
		return 'border-primary bg-primary/10 text-primary';
	}

	function dataImageUrl(payload: string | null | undefined): string | null {
		return payload ? `data:image/jpeg;base64,${payload}` : null;
	}

	function lookupLegoColor(
		color_id: string | null | undefined,
		color_name: string | null | undefined
	): LegoColor | null {
		if (color_id) {
			const by_id = LEGO_COLORS.find((c) => c.id === color_id);
			if (by_id) return by_id;
		}
		if (color_name) {
			const lower = color_name.toLowerCase();
			const by_name = LEGO_COLORS.find((c) => c.name.toLowerCase() === lower);
			if (by_name) return by_name;
		}
		return null;
	}

	function sourceBadge(img: RecognitionImage): { label: string; cls: string } {
		const ch = img.channel;
		if (img.source === 'upstream') {
			// Upstream crops come from C2 or C3; fall back to "C2/3" for older
			// records captured before the channel was recorded.
			const label = ch === 2 || ch === 3 ? `C${ch}` : 'C2/3';
			return { label, cls: 'border-warning/60 bg-warning/[0.12] text-warning' };
		}
		return { label: 'C4', cls: 'border-border bg-surface text-text-muted' };
	}

	// Badge shown on the result header when classification needed a retry. null
	// for the normal first-try (initial) path, so it only ever flags the
	// interesting case.
	function strategyBadge(
		strategy: ClassificationAttemptStrategy | null | undefined
	): { label: string } | null {
		if (!strategy || strategy === 'initial') return null;
		if (strategy === 'drop_upstream') return { label: 'RETRY · NO UPSTREAM' };
		if (strategy === 'split_singles') return { label: 'RETRY · SPLIT' };
		return { label: `RETRY · ${strategy}` };
	}

	// One chip per Brickognize attempt for the attempts strip. The applied one is
	// highlighted; misses and errors read muted.
	function attemptChip(a: ClassificationAttempt): { text: string; cls: string } {
		const name = a.label ?? a.strategy;
		const outcome = a.error
			? 'error'
			: a.found
				? `${((a.confidence ?? 0) * 100).toFixed(0)}%`
				: 'miss';
		const cls = a.applied
			? 'border-primary/60 bg-primary/[0.12] text-primary'
			: 'border-border bg-surface text-text-muted';
		return { text: `${name}: ${outcome}${a.applied ? ' ✓' : ''}`, cls };
	}

	// Per-image visual state: produced the applied result, sent-then-dropped on a
	// retry, or never shipped.
	function imageState(img: RecognitionImage): 'used' | 'dropped' | 'unsent' {
		if (img.used) return 'used';
		if (img.excluded_from_result) return 'dropped';
		return 'unsent';
	}

	// C4 burst frames first, then upstream matches — read left-to-right as
	// "what the camera saw" followed by "what we pulled from upstream".
	function sortImages(images: RecognitionImage[]): RecognitionImage[] {
		return [...images].sort((a, b) => {
			if (a.source !== b.source) return a.source === 'c4_burst' ? -1 : 1;
			return (a.ts ?? 0) - (b.ts ?? 0);
		});
	}

	function imageCounts(images: RecognitionImage[]): { c4: number; upstream: number } {
		let c4 = 0;
		let upstream = 0;
		for (const img of images) {
			if (img.source === 'upstream') upstream += 1;
			else c4 += 1;
		}
		return { c4, upstream };
	}

	// Latest C4 burst capture timestamp for a piece — the moment the
	// classification chamber snapped its pics. Used to age upstream crops.
	function c4ReferenceTs(images: RecognitionImage[]): number | null {
		let ref: number | null = null;
		for (const img of images) {
			if (img.source !== 'upstream' && typeof img.ts === 'number') {
				ref = ref === null ? img.ts : Math.max(ref, img.ts);
			}
		}
		return ref;
	}

	function imageInfoRows(
		img: RecognitionImage,
		c4RefTs: number | null
	): { label: string; value: string }[] {
		const shipped =
			img.used
				? 'Yes — used for result'
				: img.excluded_from_result
					? 'Sent, then dropped on retry'
					: 'No';
		const rows: { label: string; value: string }[] = [
			{ label: 'Source', value: img.source === 'upstream' ? 'Upstream (C2/C3)' : 'C4 burst' },
			{ label: 'Shipped', value: shipped }
		];
		if (img.source === 'upstream' && typeof img.score === 'number') {
			rows.push({ label: 'Similarity', value: `${(img.score * 100).toFixed(0)}%` });
		}
		if (img.source === 'upstream' && typeof img.ts === 'number' && c4RefTs !== null) {
			const age = c4RefTs - img.ts;
			rows.push({ label: 'Age before C4', value: `${age.toFixed(1)}s` });
		}
		return rows;
	}

	function formatDuration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0h 0m';
		const total_min = Math.floor(seconds / 60);
		const days = Math.floor(total_min / 1440);
		const hours = Math.floor((total_min % 1440) / 60);
		const mins = total_min % 60;
		if (days > 0) return `${days}d ${hours}h`;
		return `${hours}h ${mins}m`;
	}

	function formatHours(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '0';
		return (seconds / 3600).toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	function formatPpm(ppm: number | null | undefined): string {
		if (!ppm || ppm <= 0) return '—';
		return ppm.toLocaleString(undefined, { maximumFractionDigits: 1 });
	}

	let utilizationPct = $derived(
		lifetime && lifetime.seconds_powered > 0
			? (lifetime.seconds_sorted / lifetime.seconds_powered) * 100
			: 0
	);

	function formatDayLabel(day: string): string {
		const d = new Date(`${day}T00:00:00`);
		if (Number.isNaN(d.getTime())) return day;
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	onMount(() => {
		refresh();
	});
</script>

<svelte:head>
	<title>Records · Sorter</title>
</svelte:head>

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

		{#snippet statCard(label: string, value: string)}
			<div class="border border-border bg-surface px-4 py-3">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">{label}</div>
				<div class="mt-1 text-2xl font-bold text-text">{value}</div>
			</div>
		{/snippet}
		{#snippet statCardSub(label: string, value: string, sub: string)}
			<div class="border border-border bg-surface px-4 py-3">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">{label}</div>
				<div class="mt-1 text-2xl font-bold text-text">{value}</div>
				<div class="mt-0.5 text-sm text-text-muted">{sub}</div>
			</div>
		{/snippet}

		<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">Lifetime</h3>
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			{@render statCardSub(
				'Hours sorted',
				lifetime ? formatHours(lifetime.seconds_sorted) : '—',
				lifetime ? formatDuration(lifetime.seconds_sorted) + ' active' : ''
			)}
			{@render statCardSub(
				'Hours powered',
				lifetime ? formatHours(lifetime.seconds_powered) : '—',
				lifetime ? formatDuration(lifetime.seconds_powered) + ' on' : ''
			)}
			{@render statCard('Utilization', lifetime ? `${utilizationPct.toFixed(0)}%` : '—')}
			{@render statCard('Active days', lifetime ? lifetime.active_days.toLocaleString() : '—')}
			{@render statCard(
				'Pieces sorted',
				lifetime ? lifetime.pieces_distributed.toLocaleString() : '—'
			)}
			{@render statCardSub(
				'Throughput',
				lifetime ? formatPpm(lifetime.overall_ppm) : '—',
				'avg pieces/min'
			)}
			{@render statCardSub(
				'Best hour',
				lifetime ? formatPpm(lifetime.best_hour_ppm) : '—',
				'peak pieces/min'
			)}
			{@render statCard(
				'Classified',
				lifetime ? lifetime.pieces_classified.toLocaleString() : '—'
			)}
		</div>

		{#if lifetime && lifetime.daily.length > 0}
			<div class="overflow-x-auto border border-border">
				<table class="w-full border-collapse text-sm">
					<thead>
						<tr class="border-b border-border bg-surface text-left text-text-muted">
							<th class="px-3 py-2 font-semibold">Day</th>
							<th class="px-3 py-2 font-semibold">Powered</th>
							<th class="px-3 py-2 font-semibold">Sorted</th>
							<th class="px-3 py-2 font-semibold">Pieces</th>
							<th class="px-3 py-2 font-semibold">Classified</th>
							<th class="px-3 py-2 font-semibold">PPM</th>
						</tr>
					</thead>
					<tbody>
						{#each lifetime.daily as d (d.day)}
							<tr class="border-b border-border last:border-b-0 hover:bg-surface">
								<td class="px-3 py-2 text-text">{formatDayLabel(d.day)}</td>
								<td class="px-3 py-2 text-text-muted">{formatDuration(d.seconds_powered)}</td>
								<td class="px-3 py-2 text-text">{formatDuration(d.seconds_sorted)}</td>
								<td class="px-3 py-2 text-text">{d.pieces_distributed.toLocaleString()}</td>
								<td class="px-3 py-2 text-text-muted">{d.pieces_classified.toLocaleString()}</td>
								<td class="px-3 py-2 text-text">
									{formatPpm(d.seconds_sorted > 0 ? (d.pieces_distributed * 60) / d.seconds_sorted : 0)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">History</h3>
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			{@render statCard('Pieces seen', overview ? overview.total_pieces.toLocaleString() : '—')}
			{@render statCard(
				'Classified',
				overview ? overview.classified_pieces.toLocaleString() : '—'
			)}
			{@render statCard(
				'Distributed',
				overview ? overview.distributed_pieces.toLocaleString() : '—'
			)}
			{@render statCard('Runs', overview ? overview.total_runs.toLocaleString() : '—')}
			{@render statCard('Unique parts', overview ? overview.unique_parts.toLocaleString() : '—')}
			{@render statCard('Unique colors', overview ? overview.unique_colors.toLocaleString() : '—')}
			{@render statCard('First seen', overview ? formatDate(overview.first_seen) : '—')}
			{@render statCard('Last seen', overview ? formatDate(overview.last_seen) : '—')}
		</div>

		<div class="flex items-center justify-between gap-3">
			<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">
				Pieces
			</h3>
			<div class="flex items-center gap-3 text-sm text-text-muted">
				<span>
					{#if total > 0}
						{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
					{:else}
						0 records
					{/if}
				</span>
				<div class="flex border border-border">
					<button
						type="button"
						onclick={prevPage}
						disabled={offset <= 0 || loading}
						aria-label="Previous page"
						class="border-r border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronLeft size={14} />
					</button>
					<span class="px-3 py-1 text-text">{pageNum} / {pageCount}</span>
					<button
						type="button"
						onclick={nextPage}
						disabled={offset + PAGE_SIZE >= total || loading}
						aria-label="Next page"
						class="border-l border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronRight size={14} />
					</button>
				</div>
			</div>
		</div>

		{#if pieces.length === 0}
			<div class="border border-border bg-surface p-8 text-center text-sm text-text-muted">
				{loading ? 'Loading…' : 'No records yet.'}
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				{#each pieces as p (p.uuid)}
					{@const img_state = imagesByUuid[p.uuid]}
					{@const sorted = img_state?.status === 'ok' ? sortImages(img_state.images) : []}
					{@const counts = imageCounts(sorted)}
					{@const c4RefTs = c4ReferenceTs(sorted)}
					{@const lego_color = lookupLegoColor(p.color_id, p.color_name)}
					<div class="border border-border bg-surface">
						<!-- Result header -->
						<div class="flex flex-wrap items-center gap-2 border-b border-border bg-bg px-3 py-2">
							<span
								class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider {statusChipClass(
									p.classification_status
								)}"
							>
								{formatStatus(p.classification_status)}
							</span>

							<span class="truncate text-sm font-semibold text-text">
								{p.part_name ?? p.part_id ?? p.uuid.slice(0, 8)}
							</span>
							{#if p.part_id && p.part_name}
								<span class="font-mono text-xs text-text-muted">{p.part_id}</span>
							{/if}

							{#if typeof p.confidence === 'number'}
								<span class="text-sm font-semibold tabular-nums {confidenceClass(p.confidence)}">
									{formatConfidence(p.confidence)}
								</span>
							{/if}

							{#if img_state?.status === 'ok'}
								{@const sb = strategyBadge(img_state.strategy)}
								{#if sb}
									<span
										class="inline-flex items-center border border-info/60 bg-info/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-info"
										title="Brickognize recognized this piece only after a retry with a reduced image set"
									>
										{sb.label}
									</span>
								{/if}
							{/if}

							{#if lego_color}
								<span
									class="inline-flex items-center border border-border px-1.5 py-0.5 text-xs font-semibold"
									style:background-color={lego_color.hex}
									style:color={lego_color.contrast === 'white' ? '#ffffff' : '#000000'}
								>
									{lego_color.name}
								</span>
							{:else if p.color_name && p.color_name !== 'Any Color'}
								<span
									class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted"
								>
									{p.color_name}
								</span>
							{/if}

							<span class="ml-auto flex items-center gap-3 text-xs text-text-muted">
								{#if img_state?.status === 'ok'}
									<span class="tabular-nums">{counts.c4} C4 · {counts.upstream} upstream</span>
								{/if}
								<span class="font-mono">{formatBin(p.destination_bin)}</span>
								<span class="tabular-nums">{formatTimestamp(p.seen_at)}</span>
								{#if img_state?.status === 'ok' && sorted.length > 0}
									<button
										type="button"
										onclick={() => toggleReclassify(p.uuid)}
										class="inline-flex items-center gap-1 {expandedReclassify.has(p.uuid)
											? 'text-warning'
											: 'text-text-muted hover:text-warning'}"
										title="Scratch reclassify — pick crops and re-run Brickognize (not recorded)"
									>
										<FlaskConical size={13} />
									</button>
								{/if}
								<a
									href={`/tracked/${p.uuid}`}
									class="inline-flex items-center gap-1 text-text-muted hover:text-primary"
									title="Open piece detail"
								>
									<ExternalLink size={13} />
								</a>
							</span>
						</div>

						<!-- Attempts strip — only when a retry happened (>1 attempt) -->
						{#if img_state?.status === 'ok' && (img_state.attempts?.length ?? 0) > 1}
							<div
								class="flex flex-wrap items-center gap-1.5 border-b border-border bg-bg px-3 py-1.5"
							>
								<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
									Attempts
								</span>
								{#each img_state.attempts ?? [] as a, ai (ai)}
									{@const chip = attemptChip(a)}
									<span class="inline-flex items-center border px-1.5 py-0.5 text-xs {chip.cls}">
										{chip.text}
									</span>
								{/each}
							</div>
						{/if}

						<!-- Image contact sheet -->
						<div class="p-3">
							{#if img_state?.status === 'loading' || img_state === undefined}
								<div class="flex items-center gap-2 text-sm text-text-muted">
									<Spinner />
									<span>Loading crops…</span>
								</div>
							{:else if img_state.status === 'missing' || sorted.length === 0}
								<div class="text-sm text-text-muted">
									Images unavailable (aged out of memory or none captured).
								</div>
							{:else}
								<div class="flex flex-wrap gap-2">
									{#each sorted as img, i (i)}
										{@const badge = sourceBadge(img)}
										{@const src = dataImageUrl(img.image)}
										{@const state = imageState(img)}
										<div
											class="relative flex flex-col border bg-white {state === 'used'
												? 'border-2 border-primary'
												: state === 'dropped'
													? 'border-2 border-danger/60'
													: 'border-border'}"
											title={state === 'used'
												? 'Used — produced the applied result'
												: state === 'dropped'
													? 'Sent in a failed attempt, then dropped for the retry'
													: 'Captured, not shipped'}
										>
											<div class="h-28 w-28 bg-white {state === 'dropped' ? 'opacity-50' : ''}">
												{#if src}
													<img
														{src}
														alt={img.source}
														class="h-full w-full object-contain"
														loading="lazy"
													/>
													<ImageInfoBadge
														class="absolute right-1 top-1 z-10"
														{src}
														rows={imageInfoRows(img, c4RefTs)}
													/>
												{/if}
											</div>
											<div
												class="flex items-center justify-between gap-1 border-t border-border px-1.5 py-1"
											>
												<span
													class="inline-flex items-center border px-1 py-0.5 text-xs font-semibold uppercase tracking-wider {badge.cls}"
												>
													{badge.label}
												</span>
												{#if state === 'dropped'}
													<span
														class="inline-flex items-center border border-danger/60 bg-danger/[0.12] px-1 py-0.5 text-xs font-semibold uppercase tracking-wider text-danger"
													>
														Dropped
													</span>
												{:else if img.source === 'upstream' && typeof img.score === 'number'}
													<span class="text-xs tabular-nums text-text-muted">
														{(img.score * 100).toFixed(0)}%
													</span>
												{/if}
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>

						{#if expandedReclassify.has(p.uuid) && img_state?.status === 'ok'}
							<div class="border-t border-border p-3">
								<ReclassifyPanel
									endpointBase={effectiveBase()}
									images={sorted.map((img) => ({
										image: img.image,
										label: img.source === 'upstream' ? 'Upstream' : 'C4 burst',
										used: img.used,
										score: img.score
									}))}
								/>
							</div>
						{/if}
					</div>
				{/each}
			</div>

			<div class="flex items-center justify-end gap-3 text-sm text-text-muted">
				<span>
					{#if total > 0}
						{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
					{:else}
						0 records
					{/if}
				</span>
				<div class="flex border border-border">
					<button
						type="button"
						onclick={prevPage}
						disabled={offset <= 0 || loading}
						aria-label="Previous page"
						class="border-r border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronLeft size={14} />
					</button>
					<span class="px-3 py-1 text-text">{pageNum} / {pageCount}</span>
					<button
						type="button"
						onclick={nextPage}
						disabled={offset + PAGE_SIZE >= total || loading}
						aria-label="Next page"
						class="border-l border-border px-2 py-1 text-text-muted hover:text-text disabled:opacity-40"
					>
						<ChevronRight size={14} />
					</button>
				</div>
			</div>
		{/if}
	</div>
</div>
