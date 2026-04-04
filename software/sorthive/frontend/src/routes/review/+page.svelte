<script lang="ts">
	import { onMount } from 'svelte';
	import {
		api,
		type SampleClassificationPayload,
		type SampleDetail,
		type SampleReview,
		type SavedSampleAnnotation
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import SampleAnnotator, { type SeedBox } from '$lib/components/SampleAnnotator.svelte';
	import SampleClassificationCard from '$lib/components/SampleClassificationCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { AnnotatorApi } from '$lib/components/annotator-api.svelte';
	import { ClassificationApi } from '$lib/components/classification-api.svelte';

	type ReviewDecision = 'accept' | 'reject';
	type Bbox = { x: number; y: number; w: number; h: number };

	const annotatorApi = new AnnotatorApi();
	const classificationApi = new ClassificationApi();

	const proposalPalette = [
		{ stroke: '#22c55e', fill: 'rgba(34, 197, 94, 0.10)' },
		{ stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.10)' },
		{ stroke: '#f97316', fill: 'rgba(249, 115, 22, 0.10)' },
		{ stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.10)' },
		{ stroke: '#eab308', fill: 'rgba(234, 179, 8, 0.10)' },
		{ stroke: '#ef4444', fill: 'rgba(239, 68, 68, 0.10)' }
	] as const;

	let sample = $state<SampleDetail | null>(null);
	let reviews = $state<SampleReview[]>([]);
	let loading = $state(true);
	let submitting = $state(false);
	let empty = $state(false);
	let error = $state<string | null>(null);
	let feedback = $state<string | null>(null);
	let currentDecision = $state<ReviewDecision | null>(null);
	let annotateMode = $state(false);
	let showBboxOverlay = $state(true);
	let imageNaturalWidth = $state(0);
	let imageNaturalHeight = $state(0);
	let reviewHistory = $state<string[]>([]);
	let lastLoadedReviewKey = $state<string | null>(null);

	function parseBbox(b: unknown): Bbox | null {
		if (Array.isArray(b) && b.length >= 4) {
			const [x1, y1, x2, y2] = b;
			if ([x1, y1, x2, y2].every((value) => typeof value === 'number')) {
				return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
			}
		}
		if (
			b &&
			typeof b === 'object' &&
			'x' in b &&
			'y' in b &&
			'w' in b &&
			'h' in b &&
			typeof b.x === 'number' &&
			typeof b.y === 'number' &&
			typeof b.w === 'number' &&
			typeof b.h === 'number'
		) {
			return { x: b.x, y: b.y, w: b.w, h: b.h };
		}
		return null;
	}

	function parseBboxCollection(raw: unknown): Bbox[] {
		if (Array.isArray(raw)) {
			if (raw.length >= 4 && typeof raw[0] === 'number') {
				const single = parseBbox(raw);
				return single ? [single] : [];
			}
			return raw.map(parseBbox).filter((bbox): bbox is Bbox => bbox !== null);
		}
		if (raw && typeof raw === 'object') {
			const single = parseBbox(raw);
			return single ? [single] : [];
		}
		return [];
	}

	function proposalColor(index: number) {
		return proposalPalette[index % proposalPalette.length];
	}

	function isTextInputTarget(target: EventTarget | null) {
		if (!(target instanceof HTMLElement)) return false;
		return (
			target instanceof HTMLInputElement ||
			target instanceof HTMLTextAreaElement ||
			target.isContentEditable
		);
	}

	const extra = $derived(sample?.extra_metadata ?? {});
	const detectionFound = $derived(
		typeof extra.detection_found === 'boolean' ? extra.detection_found : null
	);
	const detectionScope = $derived(
		typeof extra.detection_scope === 'string' ? extra.detection_scope : null
	);
	const camera = $derived(typeof extra.camera === 'string' ? extra.camera : null);

	const primaryBboxes = $derived.by(() => {
		const direct = parseBboxCollection(sample?.detection_bboxes);
		return direct.length > 0 ? direct : parseBboxCollection(extra.detection_bbox);
	});

	const candidateBboxes = $derived.by(() => parseBboxCollection(extra.detection_candidate_bboxes));

	const legacyReviewBboxes = $derived.by(() => {
		const review = extra.review;
		if (!review || typeof review !== 'object') return [] as Bbox[];
		const corrections = (review as Record<string, unknown>).box_corrections;
		if (!Array.isArray(corrections)) return [] as Bbox[];
		return corrections
			.map((entry) => {
				if (!entry || typeof entry !== 'object') return null;
				return parseBbox((entry as Record<string, unknown>).bbox);
			})
			.filter((bbox): bbox is Bbox => bbox !== null);
	});

	const proposalBoxes = $derived.by(() => {
		const proposals = [...primaryBboxes, ...candidateBboxes];
		return proposals.length > 0 ? proposals : legacyReviewBboxes;
	});

	const annotationSeedBoxes = $derived.by(() => {
		const seeds: SeedBox[] = proposalBoxes.map((bbox, index) => ({
			...bbox,
			source: index < primaryBboxes.length ? 'primary' : 'candidate'
		}));
		return seeds.length > 0
			? seeds
			: legacyReviewBboxes.map((bbox) => ({ ...bbox, source: 'primary' as const }));
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

	const currentUserReview = $derived.by(() => {
		const userId = auth.user?.id;
		if (!userId) return null;
		return [...reviews].reverse().find((review) => review.reviewer_id === userId) ?? null;
	});

	$effect(() => {
		const sampleId = sample?.id ?? null;
		const marker = currentUserReview
			? `${sampleId}:${currentUserReview.id}:${currentUserReview.updated_at}`
			: sampleId
				? `${sampleId}:none`
				: null;

		if (!marker || marker === lastLoadedReviewKey) return;

		currentDecision = currentUserReview?.decision ?? null;
		lastLoadedReviewKey = marker;
	});

	onMount(() => {
		void loadNext();
	});

	async function loadSample(sampleId: string) {
		loading = true;
		error = null;
		feedback = null;
		imageNaturalWidth = 0;
		imageNaturalHeight = 0;

		try {
			const [detail, history] = await Promise.all([
				api.getSample(sampleId),
				api.getReviewHistory(sampleId)
			]);
			sample = detail;
			reviews = history.reviews;
			empty = false;
			lastLoadedReviewKey = null;
		} catch (e) {
			sample = null;
			reviews = [];
			error = (e as { error?: string }).error || 'Failed to load review sample.';
		} finally {
			loading = false;
		}
	}

	async function loadNext() {
		loading = true;
		error = null;
		feedback = null;
		try {
			const next = await api.getNextReview();
			if (!next) {
				sample = null;
				reviews = [];
				currentDecision = null;
				annotateMode = false;
				empty = true;
				return;
			}
			annotateMode = false;
			await loadSample(next.id);
		} catch (e) {
			sample = null;
			reviews = [];
			empty = true;
			error = (e as { error?: string }).error || 'Failed to load review queue.';
		} finally {
			loading = false;
		}
	}

	async function goBack() {
		if (reviewHistory.length === 0 || submitting || loading) return;
		const classificationOk = await savePendingClassificationIfNeeded();
		if (!classificationOk) return;
		const annotationsOk = await savePendingAnnotationsIfNeeded();
		if (!annotationsOk) return;
		const previousId = reviewHistory[reviewHistory.length - 1];
		reviewHistory = reviewHistory.slice(0, -1);
		annotateMode = false;
		await loadSample(previousId);
	}

	async function savePendingClassificationIfNeeded() {
		if (!classificationApi.isDirty) return true;
		const saved = await classificationApi.save();
		if (!saved) {
			error = 'Classification correction could not be saved. Please fix that first.';
		}
		return saved;
	}

	async function savePendingAnnotationsIfNeeded() {
		if (!annotateMode || !annotatorApi.isDirty) return true;
		const saved = await annotatorApi.save();
		if (!saved) {
			error = 'Annotations could not be saved. Please fix that first.';
		}
		return saved;
	}

	async function submitReview(decision: ReviewDecision) {
		if (!sample || submitting) return;
		error = null;
		feedback = null;

		const classificationOk = await savePendingClassificationIfNeeded();
		if (!classificationOk) return;

		const annotationsOk = await savePendingAnnotationsIfNeeded();
		if (!annotationsOk) return;

		submitting = true;
		try {
			const review = await api.submitReview(sample.id, decision);
			if (reviewHistory[reviewHistory.length - 1] !== sample.id) {
				reviewHistory = [...reviewHistory, sample.id];
			}
			currentDecision = review.decision;
			feedback =
				review.decision === 'accept'
					? 'Accepted. Loading the next sample...'
					: 'Rejected. Loading the next sample...';
			await loadNext();
		} catch (e) {
			error = (e as { error?: string }).error || 'Failed to submit review.';
		} finally {
			submitting = false;
		}
	}

	async function skip() {
		if (loading || submitting) return;
		const classificationOk = await savePendingClassificationIfNeeded();
		if (!classificationOk) return;
		const annotationsOk = await savePendingAnnotationsIfNeeded();
		if (!annotationsOk) return;
		await loadNext();
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

	function toggleAnnotateMode() {
		if (!sample || loading) return;
		annotateMode = !annotateMode;
		if (annotateMode) {
			annotatorApi.activeTool = 'rectangle';
		}
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (loading || submitting) return;
		if (isTextInputTarget(event.target)) return;

		if (event.key === 'ArrowRight') {
			event.preventDefault();
			skip();
			return;
		}

		if (event.key === 'ArrowLeft') {
			event.preventDefault();
			void goBack();
			return;
		}

		if (event.key === 'ArrowUp') {
			event.preventDefault();
			void submitReview('accept');
			return;
		}

		if (event.key === 'ArrowDown') {
			event.preventDefault();
			void submitReview('reject');
			return;
		}

		if (event.key.toLowerCase() === 'd') {
			event.preventDefault();
			toggleAnnotateMode();
			return;
		}

		if (event.key === 'Escape' && annotateMode) {
			event.preventDefault();
			annotateMode = false;
		}
	}

	function onImageLoad(event: Event) {
		const image = event.target as HTMLImageElement;
		imageNaturalWidth = image.naturalWidth;
		imageNaturalHeight = image.naturalHeight;
	}

	function formatDate(value: string | null | undefined) {
		if (!value) return '—';
		return new Date(value).toLocaleString('de-DE', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function shortId(value: string) {
		return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
	}
</script>

<svelte:head>
	<title>Review - SortHive</title>
</svelte:head>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
	<div>
		<h1 class="text-2xl font-bold text-gray-900">Review Queue</h1>
		<p class="mt-1 text-sm text-gray-500">
			Arrow up accepts, arrow down rejects, arrow right skips, arrow left goes back, and <kbd class="border border-gray-300 bg-gray-50 px-1.5 py-0.5 text-[11px] font-semibold text-gray-700">D</kbd> toggles annotation.
		</p>
	</div>
</div>

{#if loading}
	<Spinner />
{:else if empty}
	<div class="border border-gray-200 bg-white p-10 text-center">
		<p class="text-lg font-medium text-gray-700">No more samples to review.</p>
		<p class="mt-2 text-sm text-gray-500">Come back later when the queue has fresh uploads again.</p>
	</div>
{:else if sample}
	{#if error}
		<div class="mb-4 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
	{/if}

	{#if feedback}
		<div class="mb-4 border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{feedback}</div>
	{/if}

	<div class="grid gap-5 lg:grid-cols-[1fr_360px]">
		<div class="min-w-0 space-y-3">
			<div class="flex flex-wrap items-center gap-2 bg-gray-50 p-1">
				<button
					type="button"
					onclick={() => {
						annotateMode = false;
					}}
					class="px-3 py-1.5 text-xs font-medium transition-colors {annotateMode ? 'text-gray-500 hover:text-gray-700' : 'bg-white text-gray-900'}"
				>
					Review
				</button>
				<button
					type="button"
					onclick={toggleAnnotateMode}
					class="px-3 py-1.5 text-xs font-medium transition-colors {annotateMode ? 'bg-white text-gray-900' : 'text-gray-500 hover:text-gray-700'}"
				>
					Annotate
				</button>

				{#if !annotateMode && proposalBoxes.length > 0}
					<div class="ml-auto flex items-center gap-1.5 pr-1">
						<label class="flex cursor-pointer items-center gap-1.5 text-xs text-gray-500 select-none">
							<input type="checkbox" bind:checked={showBboxOverlay} class="h-3 w-3 border-gray-300 text-[#0055BF]" />
							Boxes
						</label>
					</div>
				{/if}
			</div>

			{#if annotateMode}
				<SampleAnnotator
					sampleId={sample.id}
					imageUrl={api.sampleImageUrl(sample.id)}
					imageAlt={`Review sample ${sample.local_sample_id}`}
					imageWidth={sample.image_width}
					imageHeight={sample.image_height}
					seedBoxes={annotationSeedBoxes}
					persistedAnnotations={savedAnnotations}
					hasPersistedAnnotations={hasPersistedAnnotations}
					isActive={annotateMode}
					externalApi={annotatorApi}
				/>
			{:else}
				<div class="overflow-hidden border border-gray-200 bg-gray-950">
					<div class="relative">
						<img
							src={api.sampleImageUrl(sample.id)}
							alt={`Review sample ${sample.local_sample_id}`}
							class="w-full"
							onload={onImageLoad}
						/>

						{#if showBboxOverlay && imageNaturalWidth > 0 && proposalBoxes.length > 0}
							<svg
								class="pointer-events-none absolute inset-0 h-full w-full"
								viewBox="0 0 {imageNaturalWidth} {imageNaturalHeight}"
								preserveAspectRatio="xMidYMid meet"
							>
								{#each proposalBoxes as bbox, index}
									{@const color = proposalColor(index)}
									<rect
										x={bbox.x}
										y={bbox.y}
										width={bbox.w}
										height={bbox.h}
										fill={color.fill}
										stroke={color.stroke}
										stroke-width="2"
									/>
									<rect x={bbox.x} y={bbox.y - 18} width={52} height={18} fill="rgba(0,0,0,0.6)" rx="2" />
									<text
										x={bbox.x + 5}
										y={bbox.y - 5}
										fill={color.stroke}
										font-size="11"
										font-family="monospace"
									>
										box {index + 1}
									</text>
								{/each}
							</svg>
						{/if}
					</div>
				</div>
			{/if}
		</div>

		<div class="space-y-4">
			<div class="border border-gray-200 bg-white p-4">
				<div class="flex flex-wrap items-center gap-2">
					<Badge text={sample.review_status} variant="info" />
					{#if currentDecision}
						<Badge text={`You: ${currentDecision}`} variant={currentDecision === 'accept' ? 'success' : 'danger'} />
					{/if}
					{#if sample.source_role}
						<Badge text={sample.source_role} variant="neutral" />
					{/if}
				</div>

				<div class="mt-3 space-y-2 text-sm">
					<div class="flex items-center justify-between gap-3">
						<span class="text-gray-500">Sample</span>
						<span class="font-medium text-gray-900" title={sample.local_sample_id}>{shortId(sample.local_sample_id)}</span>
					</div>
					<div class="flex items-center justify-between gap-3">
						<span class="text-gray-500">Captured</span>
						<span class="text-right text-gray-900">{formatDate(sample.captured_at)}</span>
					</div>
					<div class="flex items-center justify-between gap-3">
						<span class="text-gray-500">Uploaded</span>
						<span class="text-right text-gray-900">{formatDate(sample.uploaded_at)}</span>
					</div>
					{#if sample.capture_reason}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Reason</span>
							<span class="text-right text-gray-900">{sample.capture_reason}</span>
						</div>
					{/if}
					{#if camera}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Camera</span>
							<span class="text-right text-gray-900">{camera}</span>
						</div>
					{/if}
					{#if detectionScope}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Scope</span>
							<span class="text-right text-gray-900">{detectionScope}</span>
						</div>
					{/if}
					{#if sample.detection_algorithm}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Detection</span>
							<span class="text-right text-gray-900">{sample.detection_algorithm}</span>
						</div>
					{/if}
					{#if sample.detection_score != null}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Score</span>
							<span class="text-right text-gray-900">{sample.detection_score.toFixed(2)}</span>
						</div>
					{/if}
					{#if proposalBoxes.length > 0}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Proposals</span>
							<span class="text-right font-medium text-gray-900">{proposalBoxes.length}</span>
						</div>
					{/if}
					{#if detectionFound !== null}
						<div class="flex items-center justify-between gap-3">
							<span class="text-gray-500">Found</span>
							<span class={detectionFound ? 'font-medium text-emerald-600' : 'font-medium text-red-600'}>
								{detectionFound ? 'Yes' : 'No'}
							</span>
						</div>
					{/if}
				</div>
			</div>

			<SampleClassificationCard
				sampleId={sample.id}
				sourceRole={sample.source_role}
				captureReason={sample.capture_reason}
				extraMetadata={sample.extra_metadata}
				externalApi={classificationApi}
				onSaved={handleClassificationSaved}
			/>

			<div class="border border-gray-200 bg-white p-4">
				<div class="space-y-2 text-xs">
					<div class="flex items-center justify-center gap-2">
						<button
							type="button"
							onclick={toggleAnnotateMode}
							disabled={loading || submitting}
							class="inline-flex items-center gap-2 border px-2.5 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 {annotateMode ? 'border-[#0055BF]/30 bg-[#0055BF]/10' : 'border-[#0055BF]/20 bg-sky-50 hover:bg-sky-100'}"
						>
							<div class="border border-[#0055BF]/30 bg-white px-2 py-1 text-[11px] font-bold text-[#0055BF]">
								D
							</div>
							<div>
								<div class="font-medium text-[#0055BF]">Annotate</div>
								<div class="text-[11px] text-[#0055BF]">Toggle edit mode</div>
							</div>
						</button>
						<button
							type="button"
							onclick={() => {
								annotateMode = false;
							}}
							disabled={!annotateMode || loading || submitting}
							class="inline-flex items-center gap-2 border border-gray-200 bg-gray-50 px-2.5 py-2 text-left transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
						>
							<div class="border border-gray-300 bg-white px-2 py-1 text-[11px] font-bold text-gray-700">
								Esc
							</div>
							<div>
								<div class="font-medium text-gray-900">Close</div>
								<div class="text-[11px] text-gray-600">Exit annotate</div>
							</div>
						</button>
					</div>

					<div class="mx-auto grid max-w-[210px] grid-cols-3 gap-1.5">
						<div></div>
						<button
							type="button"
							onclick={() => void submitReview('accept')}
							disabled={loading || submitting}
							class="border border-emerald-200 bg-emerald-50 px-3 py-3 text-center transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
						>
							<div class="text-2xl font-bold text-emerald-700">↑</div>
							<div class="mt-0.5 font-medium text-emerald-900">Accept</div>
						</button>
						<div></div>

						<button
							type="button"
							onclick={() => void goBack()}
							disabled={reviewHistory.length === 0 || loading || submitting}
							class="border border-gray-200 bg-gray-50 px-2 py-2 text-center transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
						>
							<div class="text-xl font-bold text-gray-700">←</div>
							<div class="mt-0.5 font-medium text-gray-900">Back</div>
						</button>
						<button
							type="button"
							onclick={() => void submitReview('reject')}
							disabled={loading || submitting}
							class="border border-red-200 bg-red-50 px-3 py-3 text-center transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
						>
							<div class="text-2xl font-bold text-red-700">↓</div>
							<div class="mt-0.5 font-medium text-red-900">Reject</div>
						</button>
						<button
							type="button"
							onclick={skip}
							disabled={loading || submitting}
							class="border border-gray-200 bg-gray-50 px-2 py-2 text-center transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
						>
							<div class="text-xl font-bold text-gray-700">→</div>
							<div class="mt-0.5 font-medium text-gray-900">Skip</div>
						</button>
					</div>

					<p class="text-center text-[11px] text-gray-500">
						Green means keep it, red means reject it, and gray moves through the queue.
					</p>
					{#if reviewHistory.length > 0}
						<p class="mt-2 text-center text-xs text-gray-400">{reviewHistory.length} reviewed this session</p>
					{/if}
				</div>
			</div>

			<div class="border border-amber-200 bg-amber-50 p-4">
				<h2 class="text-sm font-semibold text-amber-900">What Counts As Good Training Data</h2>
				<div class="mt-3 space-y-3 text-sm text-amber-900">
					<p>
						Accept only images where every visible LEGO part is covered by a box or corrected annotation.
					</p>
					<div class="border border-emerald-200 bg-white px-3 py-3">
						<div class="text-xs font-semibold tracking-wide text-emerald-700 uppercase">Accept</div>
						<p class="mt-1 text-sm text-gray-700">
							All visible parts are fully accounted for, and the boxes match the actual objects well enough for training.
						</p>
					</div>
					<div class="border border-[#0055BF]/20 bg-white px-3 py-3">
						<div class="text-xs font-semibold tracking-wide text-[#0055BF] uppercase">Annotate First</div>
						<p class="mt-1 text-sm text-gray-700">
							If parts are missing, split incorrectly, or boxed poorly, fix the annotations before accepting.
						</p>
					</div>
					<div class="border border-red-200 bg-white px-3 py-3">
						<div class="text-xs font-semibold tracking-wide text-red-700 uppercase">Reject</div>
						<p class="mt-1 text-sm text-gray-700">
							Reject images that stay incomplete or unreliable, for example when visible parts cannot be marked cleanly enough for training.
						</p>
					</div>
				</div>
			</div>

			{#if annotateMode}
				<div class="border border-gray-200 bg-white p-4">
					<div class="mb-3 flex items-center justify-between">
						<h2 class="text-sm font-semibold text-gray-900">Annotator</h2>
						<span class="text-xs font-medium {annotatorApi.isDirty ? 'text-amber-600' : annotatorApi.hasSavedBaseline ? 'text-emerald-600' : 'text-gray-400'}">
							{#if annotatorApi.isDirty}
								Unsaved
							{:else if annotatorApi.hasSavedBaseline}
								Saved
							{:else}
								Not saved
							{/if}
						</span>
					</div>

					<div class="grid grid-cols-4 gap-1.5">
						<button onclick={annotatorApi.undo} class="border border-gray-200 px-2 py-2 text-[11px] text-gray-600 hover:bg-gray-50">Undo</button>
						<button onclick={annotatorApi.redo} class="border border-gray-200 px-2 py-2 text-[11px] text-gray-600 hover:bg-gray-50">Redo</button>
						<button
							onclick={annotatorApi.deleteSelected}
							disabled={annotatorApi.selectedCount === 0}
							class="border border-red-200 px-2 py-2 text-[11px] text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-300"
						>
							Delete
						</button>
						<button onclick={annotatorApi.clearAll} class="border border-orange-200 px-2 py-2 text-[11px] text-orange-600 hover:bg-orange-50">Clear</button>
					</div>

					<div class="mt-3 inline-flex border border-gray-200 bg-gray-50 p-1">
						<button
							type="button"
							onclick={() => {
								annotatorApi.activeTool = 'rectangle';
							}}
							class="px-3 py-1.5 text-xs font-medium transition-colors {annotatorApi.activeTool === 'rectangle' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'}"
						>
							Rectangle
						</button>
						<button
							type="button"
							onclick={() => {
								annotatorApi.activeTool = 'polygon';
							}}
							class="px-3 py-1.5 text-xs font-medium transition-colors {annotatorApi.activeTool === 'polygon' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'}"
						>
							Polygon
						</button>
					</div>

					<div class="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
						<div class="bg-gray-50 px-2 py-2">
							<div class="text-sm font-semibold text-gray-900">{annotatorApi.totalAnnotations}</div>
							<div class="text-gray-400">Total</div>
						</div>
						<div class="bg-gray-50 px-2 py-2">
							<div class="text-sm font-semibold text-gray-900">{annotatorApi.seededCount}</div>
							<div class="text-gray-400">Seeded</div>
						</div>
						<div class="bg-gray-50 px-2 py-2">
							<div class="text-sm font-semibold text-gray-900">{annotatorApi.manualCount}</div>
							<div class="text-gray-400">Manual</div>
						</div>
					</div>

					<div class="mt-3 flex gap-2">
						<button
							type="button"
							onclick={annotatorApi.revert}
							class="flex-1 border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
						>
							Revert
						</button>
						{#if annotatorApi.hasSeedBoxes}
							<button
								type="button"
								onclick={annotatorApi.loadSorterBoxes}
								class="flex-1 border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
							>
								Reset
							</button>
						{/if}
					</div>

					{#if annotatorApi.feedback}
						<p class="mt-3 px-3 py-2 text-xs {annotatorApi.feedbackTone === 'danger' ? 'bg-red-50 text-red-700' : annotatorApi.feedbackTone === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-50 text-gray-600'}">
							{annotatorApi.feedback}
						</p>
					{/if}

					<button
						type="button"
						onclick={annotatorApi.save}
						disabled={annotatorApi.saving || !annotatorApi.isDirty}
						class="mt-3 flex w-full items-center justify-center px-3 py-2 text-xs font-medium text-white transition-colors disabled:cursor-not-allowed disabled:bg-[#D01012]/40 {annotatorApi.saving || !annotatorApi.isDirty ? 'bg-[#D01012]/40' : 'bg-[#D01012] hover:bg-[#B00E10]'}"
					>
						{annotatorApi.saving ? 'Saving...' : 'Save Annotations'}
					</button>
				</div>
			{/if}

		</div>
	</div>
{/if}
