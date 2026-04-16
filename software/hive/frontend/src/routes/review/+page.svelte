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
	import ReviewImageViewer from '$lib/components/review/ReviewImageViewer.svelte';
	import ReviewActionPad from '$lib/components/review/ReviewActionPad.svelte';
	import ReviewAnnotatorPanel from '$lib/components/review/ReviewAnnotatorPanel.svelte';
	import ReviewHeuristics from '$lib/components/review/ReviewHeuristics.svelte';
	import { Alert } from '$lib/components/primitives';
	import { extractLegacyReviewBboxes, extractPrimaryBboxes, parseBboxCollection, proposalColor } from '$lib/components/sample/bbox-helpers';

	type ReviewDecision = 'accept' | 'reject';
	type ReviewImageAsset = 'image' | 'full_frame';

	const annotatorApi = new AnnotatorApi();
	const classificationApi = new ClassificationApi();

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
	let lastSampleId = $state<string | null>(null);
	let reviewImageAsset = $state<ReviewImageAsset>('image');

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

	const primaryBboxes = $derived(extractPrimaryBboxes(sample?.detection_bboxes, extra.detection_bbox));
	const candidateBboxes = $derived(parseBboxCollection(extra.detection_candidate_bboxes));
	const legacyReviewBboxes = $derived(extractLegacyReviewBboxes(extra.review));

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

	const usingFullFrameFallback = $derived.by(() => {
		return Boolean(
			sample &&
			reviewImageAsset === 'full_frame' &&
			sample.has_full_frame &&
			sample.source_role === 'classification_chamber'
		);
	});

	const reviewImageUrl = $derived.by(() => {
		if (!sample) return '';
		if (reviewImageAsset === 'full_frame' && sample.has_full_frame) {
			return api.sampleFullFrameUrl(sample.id);
		}
		return api.sampleImageUrl(sample.id);
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

	$effect(() => {
		const sampleId = sample?.id ?? null;
		if (sampleId === lastSampleId) return;
		lastSampleId = sampleId;
		reviewImageAsset = 'image';
		imageNaturalWidth = 0;
		imageNaturalHeight = 0;
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
		const naturalWidth = image.naturalWidth;
		const naturalHeight = image.naturalHeight;
		const requiresFullFrameFallback =
			reviewImageAsset === 'image' &&
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
			reviewImageAsset = 'full_frame';
			imageNaturalWidth = 0;
			imageNaturalHeight = 0;
			return;
		}

		imageNaturalWidth = naturalWidth;
		imageNaturalHeight = naturalHeight;
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
	<title>Review - Hive</title>
</svelte:head>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="mb-6 flex flex-wrap items-center justify-between gap-3">
	<div>
		<h1 class="text-2xl font-bold text-text">Review Queue</h1>
		<p class="mt-1 text-sm text-text-muted">
			Arrow up accepts, arrow down rejects, arrow right skips, arrow left goes back, and <kbd class="border border-border bg-bg px-1.5 py-0.5 text-[11px] font-semibold text-text">D</kbd> toggles annotation.
		</p>
	</div>
</div>

{#if loading}
	<Spinner />
{:else if empty}
	<div class="border border-border bg-white p-10 text-center">
		<p class="text-lg font-medium text-text">No more samples to review.</p>
		<p class="mt-2 text-sm text-text-muted">Come back later when the queue has fresh uploads again.</p>
	</div>
{:else if sample}
	{#if error}
		<div class="mb-4"><Alert variant="danger">{error}</Alert></div>
	{/if}

	{#if feedback}
		<div class="mb-4"><Alert variant="success">{feedback}</Alert></div>
	{/if}

	<div class="grid gap-5 lg:grid-cols-[1fr_360px]">
		<div class="min-w-0 space-y-3">
			<div class="flex flex-wrap items-center gap-2 bg-bg p-1">
				<button
					type="button"
					onclick={() => {
						annotateMode = false;
					}}
					class="px-3 py-1.5 text-xs font-medium transition-colors {annotateMode ? 'text-text-muted hover:text-text' : 'bg-white text-text'}"
				>
					Review
				</button>
				<button
					type="button"
					onclick={toggleAnnotateMode}
					class="px-3 py-1.5 text-xs font-medium transition-colors {annotateMode ? 'bg-white text-text' : 'text-text-muted hover:text-text'}"
				>
					Annotate
				</button>

				{#if !annotateMode && proposalBoxes.length > 0}
					<div class="ml-auto flex items-center gap-1.5 pr-1">
						<label class="flex cursor-pointer items-center gap-1.5 text-xs text-text-muted select-none">
							<input type="checkbox" bind:checked={showBboxOverlay} class="h-3 w-3 border-border text-info" />
							Boxes
						</label>
					</div>
				{/if}
			</div>

			{#if annotateMode}
				<SampleAnnotator
					sampleId={sample.id}
					imageUrl={reviewImageUrl}
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
				<ReviewImageViewer
					imageUrl={reviewImageUrl}
					imageAlt={`Review sample ${sample.local_sample_id}`}
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
		</div>

		<div class="space-y-4">
			<div class="border border-border bg-white p-4">
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
						<span class="text-text-muted">Sample</span>
						<span class="font-medium text-text" title={sample.local_sample_id}>{shortId(sample.local_sample_id)}</span>
					</div>
					<div class="flex items-center justify-between gap-3">
						<span class="text-text-muted">Captured</span>
						<span class="text-right text-text">{formatDate(sample.captured_at)}</span>
					</div>
					<div class="flex items-center justify-between gap-3">
						<span class="text-text-muted">Uploaded</span>
						<span class="text-right text-text">{formatDate(sample.uploaded_at)}</span>
					</div>
					{#if sample.capture_reason}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Reason</span>
							<span class="text-right text-text">{sample.capture_reason}</span>
						</div>
					{/if}
					{#if camera}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Camera</span>
							<span class="text-right text-text">{camera}</span>
						</div>
					{/if}
					{#if detectionScope}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Scope</span>
							<span class="text-right text-text">{detectionScope}</span>
						</div>
					{/if}
					{#if sample.detection_algorithm}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Detection</span>
							<span class="text-right text-text">{sample.detection_algorithm}</span>
						</div>
					{/if}
					{#if sample.detection_score != null}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Score</span>
							<span class="text-right text-text">{sample.detection_score.toFixed(2)}</span>
						</div>
					{/if}
					{#if proposalBoxes.length > 0}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Proposals</span>
							<span class="text-right font-medium text-text">{proposalBoxes.length}</span>
						</div>
					{/if}
					{#if detectionFound !== null}
						<div class="flex items-center justify-between gap-3">
							<span class="text-text-muted">Found</span>
							<span class={detectionFound ? 'font-medium text-success' : 'font-medium text-primary'}>
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

			<ReviewActionPad
				{annotateMode}
				{loading}
				{submitting}
				reviewHistoryLength={reviewHistory.length}
				onToggleAnnotate={toggleAnnotateMode}
				onExitAnnotate={() => { annotateMode = false; }}
				onAccept={() => void submitReview('accept')}
				onReject={() => void submitReview('reject')}
				onSkip={skip}
				onBack={() => void goBack()}
			/>

			<ReviewHeuristics />

			{#if annotateMode}
				<ReviewAnnotatorPanel {annotatorApi} />
			{/if}

		</div>
	</div>
{/if}
