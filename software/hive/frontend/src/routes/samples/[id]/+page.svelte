<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { SvelteMap } from 'svelte/reactivity';
	import {
		api,
		type SampleClassificationPayload,
		type SampleDetail,
		type SampleReview,
		type SavedSampleAnnotation
	} from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import SampleAnnotator, { type SeedBox } from '$lib/components/SampleAnnotator.svelte';
	import SampleClassificationCard from '$lib/components/SampleClassificationCard.svelte';
	import { AnnotatorApi } from '$lib/components/annotator-api.svelte';
	import { auth } from '$lib/auth.svelte';
	import SampleImageViewer from '$lib/components/sample/SampleImageViewer.svelte';
	import SampleAnnotatorPanel from '$lib/components/sample/SampleAnnotatorPanel.svelte';
	import SampleConditionCard from '$lib/components/sample/SampleConditionCard.svelte';
	import SampleDetailsSidebar from '$lib/components/sample/SampleDetailsSidebar.svelte';
	import { Button } from '$lib/components/primitives';
	import { extractLegacyReviewBboxes, extractPrimaryBboxes, parseBboxCollection, proposalColor } from '$lib/components/sample/bbox-helpers';
	import {
		readSampleListContext,
		sampleListContextKey,
		sampleListContextQuery,
		sampleListFilterParams
	} from '$lib/sampleListContext';

	const annotatorApi = new AnnotatorApi();

	let sample = $state<SampleDetail | null>(null);
	let reviews = $state<SampleReview[]>([]);
	let loading = $state(true);
	let showDeleteModal = $state(false);

	// Image view toggle — persisted via ?view= query param
	type ViewMode = 'image' | 'full_frame' | 'overlay' | 'annotate';
	type ImageRenderAsset = 'image' | 'full_frame';
	const validViews: ViewMode[] = ['image', 'full_frame', 'overlay', 'annotate'];

	function readViewFromUrl(): ViewMode {
		const v = page.url.searchParams.get('view');
		if (v && validViews.includes(v as ViewMode)) return v as ViewMode;
		return 'image';
	}

	function setView(view: ViewMode) {
		activeView = view;
		if (view === 'annotate') annotatorMounted = true;
		const url = new URL(page.url);
		if (view === 'image') {
			url.searchParams.delete('view');
		} else {
			url.searchParams.set('view', view);
		}
		void goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
	}

	let activeView = $state<ViewMode>(readViewFromUrl());
	let annotatorMounted = $state(readViewFromUrl() === 'annotate');
	let showBboxOverlay = $state(true);
	let showExpandedMeta = $state(false);
	let imageNaturalWidth = $state(0);
	let imageNaturalHeight = $state(0);
	let imageRenderAsset = $state<ImageRenderAsset>('image');
	let lastLoadedSampleId = $state<string | null>(null);

	const sampleId = $derived(page.params.id);

	// List context (filters + page size) carried in the URL so reload preserves the
	// browsing context. Lets us walk to prev/next neighbours without losing filters.
	const listContext = $derived(readSampleListContext(page.url.searchParams));
	const listContextKey = $derived(sampleListContextKey(listContext));
	const listBackHref = $derived(`/samples${sampleListContextQuery(page.url.searchParams)}`);

	let neighborPages = $state(new SvelteMap<number, string[]>());
	let neighborMeta = $state<{ pages: number; total: number } | null>(null);
	let lastNeighborKey = $state('');

	const sampleLocation = $derived.by(() => {
		if (!sampleId) return null;
		for (const [pageNum, ids] of neighborPages.entries()) {
			const idx = ids.indexOf(sampleId);
			if (idx >= 0) return { pageNum, idx, ids };
		}
		return null;
	});

	const prevSampleId = $derived.by(() => {
		const loc = sampleLocation;
		if (!loc) return null;
		if (loc.idx > 0) return loc.ids[loc.idx - 1];
		const prevIds = neighborPages.get(loc.pageNum - 1);
		if (prevIds && prevIds.length > 0) return prevIds[prevIds.length - 1];
		return null;
	});

	const nextSampleId = $derived.by(() => {
		const loc = sampleLocation;
		if (!loc) return null;
		if (loc.idx < loc.ids.length - 1) return loc.ids[loc.idx + 1];
		const nextIds = neighborPages.get(loc.pageNum + 1);
		if (nextIds && nextIds.length > 0) return nextIds[0];
		return null;
	});

	const positionLabel = $derived.by(() => {
		const loc = sampleLocation;
		if (!loc || !neighborMeta) return null;
		const absoluteIndex = (loc.pageNum - 1) * listContext.page_size + loc.idx + 1;
		return `${absoluteIndex} / ${neighborMeta.total}`;
	});

	$effect(() => {
		if (listContextKey !== lastNeighborKey) {
			lastNeighborKey = listContextKey;
			neighborPages = new SvelteMap();
			neighborMeta = null;
		}
	});

	$effect(() => {
		if (!sampleId) return;
		void ensureNeighborPage(listContext.page);
	});

	$effect(() => {
		const loc = sampleLocation;
		if (!loc) return;
		if (loc.idx === 0 && loc.pageNum > 1) {
			void ensureNeighborPage(loc.pageNum - 1);
		}
		if (loc.idx === loc.ids.length - 1) {
			const totalPages = neighborMeta?.pages ?? Number.POSITIVE_INFINITY;
			if (loc.pageNum < totalPages) void ensureNeighborPage(loc.pageNum + 1);
		}
	});

	async function ensureNeighborPage(pageNum: number) {
		if (pageNum < 1) return;
		if (neighborPages.has(pageNum)) return;
		try {
			const result = await api.getSamples({
				...sampleListFilterParams(listContext),
				page: pageNum,
				page_size: listContext.page_size
			});
			// Bail if context changed under us mid-flight.
			if (sampleListContextKey(listContext) !== listContextKey) return;
			neighborPages.set(pageNum, result.items.map((s) => s.id));
			neighborMeta = { pages: result.pages, total: result.total };
		} catch {
			// ignore — neighbor info is best-effort
		}
	}

	function navigateToNeighbor(targetId: string | null) {
		if (!targetId) return;
		let targetPage = listContext.page;
		for (const [pageNum, ids] of neighborPages.entries()) {
			if (ids.includes(targetId)) {
				targetPage = pageNum;
				break;
			}
		}
		const sp = new URLSearchParams(page.url.searchParams);
		if (targetPage <= 1) sp.delete('page');
		else sp.set('page', String(targetPage));
		const search = sp.toString();
		void goto(`/samples/${targetId}${search ? `?${search}` : ''}`, {
			noScroll: true,
			keepFocus: true
		});
	}

	function onWindowKeyDown(e: KeyboardEvent) {
		if (e.metaKey || e.ctrlKey || e.altKey) return;
		if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
		if (showDeleteModal) return;
		if (activeView === 'annotate') return;
		const target = e.target as HTMLElement | null;
		if (target) {
			const tag = target.tagName;
			if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
			if (target.isContentEditable) return;
		}
		const targetId = e.key === 'ArrowLeft' ? prevSampleId : nextSampleId;
		if (!targetId) return;
		e.preventDefault();
		navigateToNeighbor(targetId);
	}

	const statusVariant: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
		unreviewed: 'neutral',
		in_review: 'info',
		accepted: 'success',
		rejected: 'danger',
		conflict: 'warning'
	};

	const statusLabel: Record<string, string> = {
		unreviewed: 'Unreviewed',
		in_review: 'In Review',
		accepted: 'Accepted',
		rejected: 'Rejected',
		conflict: 'Conflict'
	};

	// Extract extra_metadata fields
	const extra = $derived(sample?.extra_metadata ?? {});
	const detectionFound = $derived(extra.detection_found as boolean | undefined);
	const detectionMessage = $derived(extra.detection_message as string | undefined);
	const detectionScope = $derived(extra.detection_scope as string | undefined);
	const camera = $derived(extra.camera as string | undefined);
	const pieceUuid = $derived(extra.piece_uuid as string | undefined);
	const runId = $derived(extra.run_id as string | undefined);
	const detectionOpenrouterModel = $derived(extra.detection_openrouter_model as string | undefined);
	const topBboxCount = $derived(extra.top_detection_bbox_count as number | undefined);
	const bottomBboxCount = $derived(extra.bottom_detection_bbox_count as number | undefined);
	const bboxes = $derived(extractPrimaryBboxes(sample?.detection_bboxes, extra.detection_bbox));
	const candidateBboxes = $derived(parseBboxCollection(extra.detection_candidate_bboxes));
	const legacyReviewBboxes = $derived(extractLegacyReviewBboxes(extra.review));

	const annotationSeedBoxes = $derived.by(() => {
		const seeds: SeedBox[] = [];
		for (const bbox of bboxes) {
			seeds.push({ ...bbox, source: 'primary' });
		}
		for (const bbox of candidateBboxes) {
			seeds.push({ ...bbox, source: 'candidate' });
		}
		if (seeds.length === 0) {
			for (const bbox of legacyReviewBboxes) {
				seeds.push({ ...bbox, source: 'primary' });
			}
		}
		return seeds;
	});

	const proposalBoxes = $derived.by(() => {
		const proposals = [...bboxes, ...candidateBboxes];
		return proposals.length > 0 ? proposals : legacyReviewBboxes;
	});

	const usingFullFrameFallback = $derived.by(() => {
		return Boolean(
			sample &&
			activeView === 'image' &&
			imageRenderAsset === 'full_frame' &&
			sample.has_full_frame &&
			sample.source_role === 'classification_chamber'
		);
	});

	const effectiveImageUrl = $derived.by(() => {
		if (!sample) return '';
		if (imageRenderAsset === 'full_frame' && sample.has_full_frame) {
			return api.sampleFullFrameUrl(sample.id);
		}
		return api.sampleImageUrl(sample.id);
	});

	const savedAnnotations = $derived.by(() => {
		const raw = extra.manual_annotations;
		if (!raw || typeof raw !== 'object') return [] as SavedSampleAnnotation[];
		const annotations = (raw as Record<string, unknown>).annotations;
		if (!Array.isArray(annotations)) return [] as SavedSampleAnnotation[];
		return annotations.filter((annotation): annotation is SavedSampleAnnotation => {
			return Boolean(
				annotation &&
					typeof annotation === 'object' &&
					'id' in annotation &&
					'shape_type' in annotation &&
					'source' in annotation
			);
		});
	});

	const hasPersistedAnnotations = $derived.by(() => {
		const raw = extra.manual_annotations;
		return Boolean(raw && typeof raw === 'object' && 'annotations' in raw);
	});

	const extraKeys = $derived.by(() => {
		const skip = new Set([
			'detection_found', 'detection_message', 'detection_scope', 'camera',
			'piece_uuid', 'run_id', 'detection_openrouter_model',
			'top_detection_bbox_count', 'bottom_detection_bbox_count',
			'detection_candidate_bboxes', 'detection_bbox', 'manual_annotations',
			'source', 'distill_result', 'classification_result', 'manual_classification'
		]);
		return Object.keys(extra).filter(k => !skip.has(k)).sort();
	});

	$effect(() => {
		if (sampleId) loadSample(sampleId);
	});

	$effect(() => {
		const currentSampleId = sample?.id ?? null;
		if (currentSampleId === lastLoadedSampleId) return;
		lastLoadedSampleId = currentSampleId;
		imageRenderAsset = 'image';
		imageNaturalWidth = 0;
		imageNaturalHeight = 0;
	});

	async function loadSample(id: string) {
		loading = true;
		try {
			const [s, r] = await Promise.all([
				api.getSample(id),
				api.getReviewHistory(id)
			]);
			sample = s;
			reviews = r.reviews;
			const urlView = readViewFromUrl();
			activeView = urlView;
			annotatorMounted = urlView === 'annotate';
		} catch {
			sample = null;
		} finally {
			loading = false;
		}
	}

	async function handleDelete() {
		if (!sample) return;
		try {
			await api.deleteSample(sample.id);
			goto(listBackHref);
		} catch {
			// ignore
		}
	}

	function handleClassificationSaved(payload: SampleClassificationPayload | null) {
		if (!sample) return;
		const nextExtra = { ...(sample.extra_metadata ?? {}) };
		if (payload) {
			nextExtra.manual_classification = payload;
		} else {
			delete nextExtra.manual_classification;
		}
		sample = {
			...sample,
			extra_metadata: nextExtra
		};
	}

	function onImageLoad(e: Event) {
		const img = e.target as HTMLImageElement;
		const naturalWidth = img.naturalWidth;
		const naturalHeight = img.naturalHeight;
		const requiresFullFrameFallback =
			activeView === 'image' &&
			imageRenderAsset === 'image' &&
			sample?.source_role === 'classification_chamber' &&
			sample.has_full_frame &&
			proposalBoxes.length > 0 &&
			proposalBoxes.some(
				(bbox) =>
					bbox.x < 0 ||
					bbox.y < 0 ||
					bbox.x + bbox.w > naturalWidth ||
					bbox.y + bbox.h > naturalHeight
			);

		if (requiresFullFrameFallback) {
			imageRenderAsset = 'full_frame';
			imageNaturalWidth = 0;
			imageNaturalHeight = 0;
			return;
		}

		imageNaturalWidth = naturalWidth;
		imageNaturalHeight = naturalHeight;
	}

	function formatValue(val: unknown): string {
		if (val === null || val === undefined) return '—';
		if (typeof val === 'boolean') return val ? 'Yes' : 'No';
		if (typeof val === 'number') return Number.isInteger(val) ? String(val) : val.toFixed(4);
		if (typeof val === 'string') return val;
		return JSON.stringify(val);
	}

	function formatDate(d: string): string {
		return new Date(d).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	function shortId(id: string): string {
		if (id.length > 16) return id.slice(0, 8) + '...' + id.slice(-6);
		return id;
	}
</script>

<svelte:head>
	<title>Sample Detail - Hive</title>
</svelte:head>

<svelte:window onkeydown={onWindowKeyDown} />

{#if loading}
	<Spinner />
{:else if !sample}
	<p class="text-text-muted">Sample not found.</p>
{:else}
	<!-- Header bar -->
	<div class="mb-5 flex items-center justify-between gap-3">
		<div class="flex items-center gap-3">
			<a href={listBackHref} class="flex items-center gap-1 text-sm text-text-muted hover:text-text transition-colors">
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" /></svg>
				Samples
			</a>
			<span class="text-border">/</span>
			<span class="text-sm font-medium text-text" title={sample.local_sample_id}>{shortId(sample.local_sample_id)}</span>
		</div>
		<div class="flex items-center gap-2">
			<div class="flex items-center gap-1" title="Use ← / → to navigate samples">
				<button
					type="button"
					onclick={() => navigateToNeighbor(prevSampleId)}
					disabled={!prevSampleId}
					aria-label="Previous sample (←)"
					class="border border-border bg-white p-1.5 text-text-muted transition-colors hover:bg-bg hover:text-text disabled:cursor-not-allowed disabled:opacity-30"
				>
					<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" /></svg>
				</button>
				{#if positionLabel}
					<span class="px-1 text-[11px] text-text-muted tabular-nums">{positionLabel}</span>
				{/if}
				<button
					type="button"
					onclick={() => navigateToNeighbor(nextSampleId)}
					disabled={!nextSampleId}
					aria-label="Next sample (→)"
					class="border border-border bg-white p-1.5 text-text-muted transition-colors hover:bg-bg hover:text-text disabled:cursor-not-allowed disabled:opacity-30"
				>
					<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
				</button>
			</div>
			<Badge text={statusLabel[sample.review_status] ?? sample.review_status} variant={statusVariant[sample.review_status] ?? 'neutral'} />
			{#if sample.review_count > 0}
				<span class="text-xs text-text-muted">{sample.review_count} review{sample.review_count !== 1 ? 's' : ''}</span>
			{/if}
		</div>
	</div>

	<div class="grid gap-5 lg:grid-cols-[1fr_340px]">
		<!-- Left: Image area -->
		<div class="min-w-0 space-y-3">
			<!-- View toggle toolbar (above image) -->
			<div class="flex items-center gap-1 bg-bg p-1">
				<button
					onclick={() => setView('image')}
					class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'image' ? 'bg-white text-text' : 'text-text-muted hover:text-text'}"
				>
					Image
				</button>
				{#if sample.has_full_frame}
					<button
						onclick={() => setView('full_frame')}
						class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'full_frame' ? 'bg-white text-text' : 'text-text-muted hover:text-text'}"
					>
						Full Frame
					</button>
				{/if}
				{#if sample.has_overlay}
					<button
						onclick={() => setView('overlay')}
						class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'overlay' ? 'bg-white text-text' : 'text-text-muted hover:text-text'}"
					>
						Overlay
					</button>
				{/if}
				<button
					onclick={() => setView('annotate')}
					class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'annotate' ? 'bg-white text-text' : 'text-text-muted hover:text-text'}"
				>
					Annotate
				</button>

				{#if activeView === 'image' && proposalBoxes.length > 0}
					<div class="ml-auto flex items-center gap-1.5 pr-1">
						<label class="flex items-center gap-1.5 text-xs text-text-muted cursor-pointer select-none">
							<input type="checkbox" bind:checked={showBboxOverlay} class="h-3 w-3 border-border text-primary" />
							Boxes
						</label>
					</div>
				{/if}
			</div>

			<!-- Image viewer -->
			{#if activeView !== 'annotate'}
				<SampleImageViewer
					{sample}
					{activeView}
					{effectiveImageUrl}
					{proposalBoxes}
					{showBboxOverlay}
					{imageNaturalWidth}
					{imageNaturalHeight}
					{proposalColor}
					onload={onImageLoad}
				/>
			{/if}

			{#if usingFullFrameFallback}
				<div class="border border-border bg-bg px-3 py-2 text-xs text-text-muted">
					Showing the full-frame capture because this classification-chamber sample still carries detection boxes in full-frame coordinates.
				</div>
			{/if}

			{#if annotatorMounted}
				<div class={activeView === 'annotate' ? 'block' : 'hidden'}>
					<SampleAnnotator
						sampleId={sample.id}
						imageUrl={effectiveImageUrl}
						imageAlt={`Sample ${sample.local_sample_id}`}
						imageWidth={sample.image_width}
						imageHeight={sample.image_height}
						seedBoxes={annotationSeedBoxes}
						persistedAnnotations={savedAnnotations}
						hasPersistedAnnotations={hasPersistedAnnotations}
						isActive={activeView === 'annotate'}
						externalApi={annotatorApi}
					/>
				</div>
			{/if}

			<!-- Inline detection message (below image, only when relevant) -->
			{#if detectionMessage && activeView !== 'annotate'}
				<div class="bg-bg border border-border px-3 py-2 text-xs text-text-muted">
					{detectionMessage}
				</div>
			{/if}
		</div>

		<!-- Right sidebar -->
		<div class="space-y-3">
			<!-- Annotator controls (only in annotate mode) -->
			{#if activeView === 'annotate'}
				<SampleAnnotatorPanel {annotatorApi} />
			{/if}

			<!-- Detection summary card -->
			{#if sample.detection_algorithm || detectionFound !== undefined}
				<div class="border border-border bg-white">
					<div class="flex items-center justify-between border-b border-border px-4 py-2.5">
						<h2 class="text-xs font-semibold uppercase tracking-wider text-text-muted">Detection</h2>
						{#if detectionFound !== undefined}
							{#if detectionFound}
								<span class="inline-flex items-center gap-1.5 text-xs font-medium text-success">
									<span class="h-1.5 w-1.5 rounded-full bg-success"></span>
									Found
								</span>
							{:else}
								<span class="inline-flex items-center gap-1.5 text-xs font-medium text-primary">
									<span class="h-1.5 w-1.5 rounded-full bg-primary"></span>
									Not found
								</span>
							{/if}
						{/if}
					</div>
					<div class="px-4 py-3">
						<div class="flex flex-wrap gap-x-4 gap-y-2 text-xs">
							{#if sample.detection_algorithm}
								<div>
									<div class="text-text-muted mb-0.5">Algorithm</div>
									<div class="font-medium text-text">{sample.detection_algorithm}</div>
								</div>
							{/if}
							{#if sample.detection_count != null}
								<div>
									<div class="text-text-muted mb-0.5">Count</div>
									<div class="font-medium text-text">{sample.detection_count}</div>
								</div>
							{/if}
							{#if sample.detection_score != null}
								<div>
									<div class="text-text-muted mb-0.5">Score</div>
									<div class="font-medium text-text">{sample.detection_score.toFixed(2)}</div>
								</div>
							{/if}
							{#if proposalBoxes.length > 0}
								<div>
									<div class="text-text-muted mb-0.5">Proposals</div>
									<div class="font-medium text-text">{proposalBoxes.length}</div>
								</div>
							{/if}
						</div>
						{#if detectionOpenrouterModel}
							<div class="mt-2 text-[11px] text-text-muted font-mono truncate" title={detectionOpenrouterModel}>{detectionOpenrouterModel}</div>
						{/if}
					</div>
				</div>
			{/if}

			<SampleClassificationCard
				sampleId={sample.id}
				sourceRole={sample.source_role}
				captureReason={sample.capture_reason}
				extraMetadata={sample.extra_metadata}
				onSaved={handleClassificationSaved}
			/>

			<SampleConditionCard samplePayload={sample.sample_payload} />

			<SampleDetailsSidebar
				{sample}
				{reviews}
				{camera}
				{detectionScope}
				{pieceUuid}
				{runId}
				{extra}
				{extraKeys}
				{showExpandedMeta}
				onToggleExpandedMeta={() => { showExpandedMeta = !showExpandedMeta; }}
				{formatValue}
				{formatDate}
				{shortId}
			/>

			<!-- Actions (admin only, minimal) -->
			{#if auth.isAdmin}
				<div class="pt-1">
					<button
						onclick={() => { showDeleteModal = true; }}
						class="w-full px-3 py-2 text-xs text-text-muted hover:text-primary hover:bg-primary-light transition-colors"
					>
						Delete sample
					</button>
				</div>
			{/if}
		</div>
	</div>

	<Modal open={showDeleteModal} title="Delete Sample" onclose={() => { showDeleteModal = false; }}>
		<div class="space-y-4">
			<p class="text-sm text-text-muted">Are you sure you want to delete this sample? This action cannot be undone.</p>
			<div class="flex gap-2 justify-end">
				<Button variant="secondary" onclick={() => { showDeleteModal = false; }}>Cancel</Button>
				<Button variant="danger" onclick={handleDelete}>Delete</Button>
			</div>
		</div>
	</Modal>
{/if}
