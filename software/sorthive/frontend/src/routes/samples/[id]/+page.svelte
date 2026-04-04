<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
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

	const annotatorApi = new AnnotatorApi();

	let sample = $state<SampleDetail | null>(null);
	let reviews = $state<SampleReview[]>([]);
	let loading = $state(true);
	let showDeleteModal = $state(false);

	// Image view toggle — persisted via ?view= query param
	type ViewMode = 'image' | 'full_frame' | 'overlay' | 'annotate';
	const validViews: ViewMode[] = ['image', 'full_frame', 'overlay', 'annotate'];

	function readViewFromUrl(): ViewMode {
		const v = new URL(window.location.href).searchParams.get('view');
		if (v && validViews.includes(v as ViewMode)) return v as ViewMode;
		return 'image';
	}

	function setView(view: ViewMode) {
		activeView = view;
		if (view === 'annotate') annotatorMounted = true;
		const url = new URL(window.location.href);
		if (view === 'image') {
			url.searchParams.delete('view');
		} else {
			url.searchParams.set('view', view);
		}
		history.replaceState(history.state, '', url.pathname + url.search);
	}

	let activeView = $state<ViewMode>(readViewFromUrl());
	let annotatorMounted = $state(readViewFromUrl() === 'annotate');
	let showBboxOverlay = $state(true);
	let showExpandedMeta = $state(false);
	let imageNaturalWidth = $state(0);
	let imageNaturalHeight = $state(0);

	const sampleId = $derived(page.params.id);

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
	const proposalPalette = [
		{ stroke: '#22c55e', fill: 'rgba(34, 197, 94, 0.10)' },
		{ stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.10)' },
		{ stroke: '#f97316', fill: 'rgba(249, 115, 22, 0.10)' },
		{ stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.10)' },
		{ stroke: '#eab308', fill: 'rgba(234, 179, 8, 0.10)' },
		{ stroke: '#ef4444', fill: 'rgba(239, 68, 68, 0.10)' }
	] as const;

	// Parse bounding boxes for SVG overlay
	function parseBbox(b: any): { x: number; y: number; w: number; h: number } | null {
		if (Array.isArray(b) && b.length >= 4) {
			const [x1, y1, x2, y2] = b;
			return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
		}
		if (b && typeof b === 'object' && 'x' in b && 'y' in b && 'w' in b && 'h' in b) {
			return { x: b.x, y: b.y, w: b.w, h: b.h };
		}
		return null;
	}

	function parseBboxCollection(raw: any): { x: number; y: number; w: number; h: number }[] {
		if (Array.isArray(raw)) {
			if (raw.length >= 4 && typeof raw[0] === 'number') {
				const single = parseBbox(raw);
				return single ? [single] : [];
			}
			return raw
				.map(parseBbox)
				.filter((v): v is { x: number; y: number; w: number; h: number } => v !== null);
		}
		if (raw && typeof raw === 'object') {
			const single = parseBbox(raw);
			return single ? [single] : [];
		}
		return [];
	}

	const bboxes = $derived.by(() => {
		const primary = parseBboxCollection(sample?.detection_bboxes);
		if (primary.length > 0) return primary;
		return parseBboxCollection(extra.detection_bbox);
	});

	const candidateBboxes = $derived.by(() => {
		return parseBboxCollection(extra.detection_candidate_bboxes);
	});

	const legacyReviewBboxes = $derived.by(() => {
		const review = extra.review;
		if (!review || typeof review !== 'object') return [];
		const corrections = (review as Record<string, unknown>).box_corrections;
		if (!Array.isArray(corrections)) return [];
		return corrections
			.map((entry) => {
				if (!entry || typeof entry !== 'object') return null;
				return parseBbox((entry as Record<string, unknown>).bbox);
			})
			.filter((v): v is { x: number; y: number; w: number; h: number } => v !== null);
	});

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

	function proposalColor(index: number) {
		return proposalPalette[index % proposalPalette.length];
	}

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
			goto('/samples');
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
		imageNaturalWidth = img.naturalWidth;
		imageNaturalHeight = img.naturalHeight;
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
	<title>Sample Detail - SortHive</title>
</svelte:head>

{#if loading}
	<Spinner />
{:else if !sample}
	<p class="text-gray-500">Sample not found.</p>
{:else}
	<!-- Header bar -->
	<div class="mb-5 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href="/samples" class="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors">
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" /></svg>
				Samples
			</a>
			<span class="text-gray-300">/</span>
			<span class="text-sm font-medium text-gray-900" title={sample.local_sample_id}>{shortId(sample.local_sample_id)}</span>
		</div>
		<div class="flex items-center gap-2">
			<Badge text={statusLabel[sample.review_status] ?? sample.review_status} variant={statusVariant[sample.review_status] ?? 'neutral'} />
			{#if sample.review_count > 0}
				<span class="text-xs text-gray-400">{sample.review_count} review{sample.review_count !== 1 ? 's' : ''}</span>
			{/if}
		</div>
	</div>

	<div class="grid gap-5 lg:grid-cols-[1fr_340px]">
		<!-- Left: Image area -->
		<div class="min-w-0 space-y-3">
			<!-- View toggle toolbar (above image) -->
			<div class="flex items-center gap-1 bg-gray-50 p-1">
				<button
					onclick={() => setView('image')}
					class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'image' ? 'bg-white text-gray-900' : 'text-gray-500 hover:text-gray-700'}"
				>
					Image
				</button>
				{#if sample.has_full_frame}
					<button
						onclick={() => setView('full_frame')}
						class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'full_frame' ? 'bg-white text-gray-900' : 'text-gray-500 hover:text-gray-700'}"
					>
						Full Frame
					</button>
				{/if}
				{#if sample.has_overlay}
					<button
						onclick={() => setView('overlay')}
						class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'overlay' ? 'bg-white text-gray-900' : 'text-gray-500 hover:text-gray-700'}"
					>
						Overlay
					</button>
				{/if}
				<button
					onclick={() => setView('annotate')}
					class="px-3 py-1.5 text-xs font-medium transition-colors {activeView === 'annotate' ? 'bg-white text-gray-900' : 'text-gray-500 hover:text-gray-700'}"
				>
					Annotate
				</button>

				{#if activeView === 'image' && proposalBoxes.length > 0}
					<div class="ml-auto flex items-center gap-1.5 pr-1">
						<label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
							<input type="checkbox" bind:checked={showBboxOverlay} class="h-3 w-3 border-gray-300 text-[#D01012]" />
							Boxes
						</label>
					</div>
				{/if}
			</div>

			<!-- Image viewer -->
			{#if activeView !== 'annotate'}
				<div class="overflow-hidden border border-gray-200 bg-gray-950">
					<div class="relative">
						{#if activeView === 'image'}
							<img
								src={api.sampleImageUrl(sample.id)}
								alt="Sample"
								class="w-full"
								onload={onImageLoad}
							/>
						{:else if activeView === 'full_frame' && sample.has_full_frame}
							<img
								src={api.sampleFullFrameUrl(sample.id)}
								alt="Full frame"
								class="w-full"
							/>
						{:else if activeView === 'overlay' && sample.has_overlay}
							<img
								src={api.sampleOverlayUrl(sample.id)}
								alt="Overlay"
								class="w-full"
							/>
						{/if}

						{#if showBboxOverlay && activeView === 'image' && imageNaturalWidth > 0 && proposalBoxes.length > 0}
							<svg
								class="absolute inset-0 h-full w-full pointer-events-none"
								viewBox="0 0 {imageNaturalWidth} {imageNaturalHeight}"
								preserveAspectRatio="xMidYMid meet"
							>
								{#each proposalBoxes as bbox, i}
									{@const color = proposalColor(i)}
									<rect
										x={bbox.x} y={bbox.y} width={bbox.w} height={bbox.h}
										fill={color.fill}
										stroke={color.stroke}
										stroke-width="2"
									/>
									<rect
										x={bbox.x} y={bbox.y - 18} width={52} height={18}
										fill="rgba(0,0,0,0.6)" rx="2"
									/>
									<text
										x={bbox.x + 5} y={bbox.y - 5}
										fill={color.stroke}
										font-size="11"
										font-family="monospace"
									>box {i + 1}</text>
								{/each}
							</svg>
						{/if}
					</div>
				</div>
			{/if}

			{#if annotatorMounted}
				<div class={activeView === 'annotate' ? 'block' : 'hidden'}>
					<SampleAnnotator
						sampleId={sample.id}
						imageUrl={api.sampleImageUrl(sample.id)}
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
				<div class="bg-gray-50 border border-gray-100 px-3 py-2 text-xs text-gray-600">
					{detectionMessage}
				</div>
			{/if}
		</div>

		<!-- Right sidebar -->
		<div class="space-y-3">
			<!-- Annotator controls (only in annotate mode) -->
			{#if activeView === 'annotate'}
				<div class="border border-gray-200 bg-white">
					<div class="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
						<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Annotator</h2>
						<span class="text-[11px] font-medium {annotatorApi.isDirty ? 'text-amber-600' : annotatorApi.hasSavedBaseline ? 'text-emerald-600' : 'text-gray-400'}">
							{#if annotatorApi.isDirty}Unsaved{:else if annotatorApi.hasSavedBaseline}Saved{:else}Not saved{/if}
						</span>
					</div>
					<div class="space-y-3 p-3">
						<!-- Actions -->
						<div class="grid grid-cols-4 gap-1.5">
							<button onclick={annotatorApi.undo} class="flex flex-col items-center gap-1 border border-gray-200 px-1 py-2 text-gray-500 transition-colors hover:bg-gray-50" title="Undo">
								<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a4 4 0 014 4v0a4 4 0 01-4 4H3m0-8l4-4m-4 4l4 4" /></svg>
								<span class="text-[10px]">Undo</span>
							</button>
							<button onclick={annotatorApi.redo} class="flex flex-col items-center gap-1 border border-gray-200 px-1 py-2 text-gray-500 transition-colors hover:bg-gray-50" title="Redo">
								<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 10H11a4 4 0 00-4 4v0a4 4 0 004 4h10m0-8l-4-4m4 4l-4 4" /></svg>
								<span class="text-[10px]">Redo</span>
							</button>
							<button
								onclick={annotatorApi.deleteSelected}
								disabled={annotatorApi.selectedCount === 0}
								class="flex flex-col items-center gap-1 border px-1 py-2 transition-colors disabled:cursor-not-allowed disabled:border-gray-100 disabled:text-gray-300 {annotatorApi.selectedCount === 0 ? '' : 'border-red-200 text-red-500 hover:bg-red-50'}"
								title="Delete selected"
							>
								<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
								<span class="text-[10px]">Delete</span>
							</button>
							<button onclick={annotatorApi.clearAll} class="flex flex-col items-center gap-1 border border-orange-200 px-1 py-2 text-orange-500 transition-colors hover:bg-orange-50" title="Clear all">
								<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
								<span class="text-[10px]">Clear</span>
							</button>
						</div>

						<!-- Revert / Sorter Boxes -->
						<div class="flex gap-1.5">
							<button onclick={annotatorApi.revert} class="flex flex-1 items-center justify-center gap-1.5 border border-gray-200 px-2 py-1.5 text-[11px] text-gray-500 transition-colors hover:bg-gray-50" title="Discard changes and restore last saved state">
								<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
								Cancel
							</button>
							{#if annotatorApi.hasSeedBoxes}
								<button onclick={annotatorApi.loadSorterBoxes} class="flex flex-1 items-center justify-center gap-1.5 border border-gray-200 px-2 py-1.5 text-[11px] text-gray-500 transition-colors hover:bg-gray-50" title="Reset to original machine detections">
									<svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115.36-5.36M20 15a9 9 0 01-15.36 5.36" /></svg>
									Reset
								</button>
							{/if}
						</div>

						<!-- Stats -->
						<div class="grid grid-cols-3 gap-1 text-center">
							<div class="bg-gray-50 px-1 py-1.5">
								<div class="text-sm font-semibold text-gray-900">{annotatorApi.totalAnnotations}</div>
								<div class="text-[10px] text-gray-400">Total</div>
							</div>
							<div class="bg-gray-50 px-1 py-1.5">
								<div class="text-sm font-semibold text-gray-900">{annotatorApi.seededCount}</div>
								<div class="text-[10px] text-gray-400">Seeded</div>
							</div>
							<div class="bg-gray-50 px-1 py-1.5">
								<div class="text-sm font-semibold text-gray-900">{annotatorApi.manualCount}</div>
								<div class="text-[10px] text-gray-400">Manual</div>
							</div>
						</div>

						<!-- Feedback -->
						{#if annotatorApi.feedback}
							<p class="px-2 py-1.5 text-[11px] {annotatorApi.feedbackTone === 'danger' ? 'bg-red-50 text-red-700' : annotatorApi.feedbackTone === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-50 text-gray-600'}">
								{annotatorApi.feedback}
							</p>
						{/if}

						<!-- Save (at the bottom) -->
						<button
							onclick={annotatorApi.save}
							disabled={annotatorApi.saving || !annotatorApi.isDirty}
							class="flex w-full items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-[#D01012]/40 {annotatorApi.saving || !annotatorApi.isDirty ? 'bg-[#D01012]/40' : 'bg-[#D01012] hover:bg-[#B00E10]'}"
						>
							<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
							{annotatorApi.saving ? 'Saving...' : 'Save Annotations'}
						</button>
					</div>
				</div>
			{/if}

			<!-- Detection summary card -->
			{#if sample.detection_algorithm || detectionFound !== undefined}
				<div class="border border-gray-200 bg-white">
					<div class="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
						<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Detection</h2>
						{#if detectionFound !== undefined}
							{#if detectionFound}
								<span class="inline-flex items-center gap-1.5 text-xs font-medium text-green-600">
									<span class="h-1.5 w-1.5 rounded-full bg-green-500"></span>
									Found
								</span>
							{:else}
								<span class="inline-flex items-center gap-1.5 text-xs font-medium text-red-500">
									<span class="h-1.5 w-1.5 rounded-full bg-red-400"></span>
									Not found
								</span>
							{/if}
						{/if}
					</div>
					<div class="px-4 py-3">
						<div class="flex flex-wrap gap-x-4 gap-y-2 text-xs">
							{#if sample.detection_algorithm}
								<div>
									<div class="text-gray-400 mb-0.5">Algorithm</div>
									<div class="font-medium text-gray-900">{sample.detection_algorithm}</div>
								</div>
							{/if}
							{#if sample.detection_count != null}
								<div>
									<div class="text-gray-400 mb-0.5">Count</div>
									<div class="font-medium text-gray-900">{sample.detection_count}</div>
								</div>
							{/if}
							{#if sample.detection_score != null}
								<div>
									<div class="text-gray-400 mb-0.5">Score</div>
									<div class="font-medium text-gray-900">{sample.detection_score.toFixed(2)}</div>
								</div>
							{/if}
							{#if proposalBoxes.length > 0}
								<div>
									<div class="text-gray-400 mb-0.5">Proposals</div>
									<div class="font-medium text-gray-900">{proposalBoxes.length}</div>
								</div>
							{/if}
						</div>
						{#if detectionOpenrouterModel}
							<div class="mt-2 text-[11px] text-gray-400 font-mono truncate" title={detectionOpenrouterModel}>{detectionOpenrouterModel}</div>
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

			<!-- Sample details card -->
			<div class="border border-gray-200 bg-white">
				<div class="border-b border-gray-100 px-4 py-2.5">
					<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Details</h2>
				</div>
				<div class="divide-y divide-gray-50">
					{#if sample.source_role}
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Source</span>
							<span class="text-xs font-medium text-gray-900">{sample.source_role}</span>
						</div>
					{/if}
					{#if sample.capture_reason}
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Reason</span>
							<span class="text-xs font-medium text-gray-900">{sample.capture_reason}</span>
						</div>
					{/if}
					{#if camera}
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Camera</span>
							<span class="text-xs font-medium text-gray-900">{camera}</span>
						</div>
					{/if}
					{#if detectionScope}
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Scope</span>
							<span class="text-xs font-medium text-gray-900">{detectionScope}</span>
						</div>
					{/if}
					{#if sample.captured_at}
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Captured</span>
							<span class="text-xs text-gray-900">{formatDate(sample.captured_at)}</span>
						</div>
					{/if}
					<div class="flex items-center justify-between px-4 py-2">
						<span class="text-xs text-gray-500">Uploaded</span>
						<span class="text-xs text-gray-900">{formatDate(sample.uploaded_at)}</span>
					</div>
					{#if sample.image_width && sample.image_height}
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Size</span>
							<span class="text-xs text-gray-900">{sample.image_width}&times;{sample.image_height}</span>
						</div>
					{/if}
				</div>
			</div>

			<!-- IDs card (collapsed look) -->
			{#if pieceUuid || runId}
				<div class="border border-gray-200 bg-white">
					<div class="border-b border-gray-100 px-4 py-2.5">
						<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">IDs</h2>
					</div>
					<div class="divide-y divide-gray-50">
						<div class="flex items-center justify-between px-4 py-2">
							<span class="text-xs text-gray-500">Sample</span>
							<span class="text-[11px] font-mono text-gray-600 truncate ml-3 max-w-[200px]" title={sample.local_sample_id}>{sample.local_sample_id}</span>
						</div>
						{#if pieceUuid}
							<div class="flex items-center justify-between px-4 py-2">
								<span class="text-xs text-gray-500">Piece</span>
								<span class="text-[11px] font-mono text-gray-600 truncate ml-3 max-w-[200px]" title={pieceUuid}>{shortId(pieceUuid)}</span>
							</div>
						{/if}
						{#if runId}
							<div class="flex items-center justify-between px-4 py-2">
								<span class="text-xs text-gray-500">Run</span>
								<span class="text-[11px] font-mono text-gray-600 truncate ml-3 max-w-[200px]" title={runId}>{shortId(runId)}</span>
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Extra Metadata -->
			{#if extraKeys.length > 0}
				<div class="border border-gray-200 bg-white">
					<button
						onclick={() => { showExpandedMeta = !showExpandedMeta; }}
						class="flex w-full items-center justify-between px-4 py-2.5"
					>
						<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Metadata ({extraKeys.length})</h2>
						<svg class="h-3.5 w-3.5 text-gray-400 transition-transform {showExpandedMeta ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</button>
					{#if showExpandedMeta}
						<div class="border-t border-gray-100 divide-y divide-gray-50">
							{#each extraKeys as key}
								<div class="flex items-start justify-between gap-3 px-4 py-2">
									<span class="text-[11px] font-mono text-gray-400 shrink-0">{key}</span>
									<span class="text-[11px] text-gray-700 text-right break-all">{formatValue(extra[key])}</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<!-- Review History -->
			<div class="border border-gray-200 bg-white">
				<div class="border-b border-gray-100 px-4 py-2.5">
					<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Reviews</h2>
				</div>
				{#if reviews.length === 0}
					<div class="px-4 py-4 text-center">
						<p class="text-xs text-gray-400">No reviews yet</p>
					</div>
				{:else}
					<div class="divide-y divide-gray-50">
						{#each reviews as review (review.id)}
							<div class="px-4 py-2.5">
								<div class="flex items-center justify-between">
									<div class="flex items-center gap-2">
										<div class="flex h-5 w-5 items-center justify-center text-[10px] font-bold {review.decision === 'accept' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}">
											{review.decision === 'accept' ? '✓' : '✗'}
										</div>
										<span class="text-xs font-medium text-gray-900">{review.reviewer_display_name ?? 'Unknown'}</span>
									</div>
									<span class="text-[11px] text-gray-400">{formatDate(review.created_at)}</span>
								</div>
								{#if review.notes}
									<p class="mt-1 ml-7 text-xs text-gray-500">{review.notes}</p>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Actions (admin only, minimal) -->
			{#if auth.isAdmin}
				<div class="pt-1">
					<button
						onclick={() => { showDeleteModal = true; }}
						class="w-full px-3 py-2 text-xs text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
					>
						Delete sample
					</button>
				</div>
			{/if}
		</div>
	</div>

	<Modal open={showDeleteModal} title="Delete Sample" onclose={() => { showDeleteModal = false; }}>
		<div class="space-y-4">
			<p class="text-sm text-gray-600">Are you sure you want to delete this sample? This action cannot be undone.</p>
			<div class="flex gap-2 justify-end">
				<button
					onclick={() => { showDeleteModal = false; }}
					class="border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
				>
					Cancel
				</button>
				<button
					onclick={handleDelete}
					class="bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
				>
					Delete
				</button>
			</div>
		</div>
	</Modal>
{/if}
