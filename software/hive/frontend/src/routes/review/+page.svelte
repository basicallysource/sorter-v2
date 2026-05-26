<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
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
	import TeacherRerunButtons from '$lib/components/teacher/TeacherRerunButtons.svelte';
	import SampleConditionCard from '$lib/components/sample/SampleConditionCard.svelte';
	import SampleConditionTagger from '$lib/components/sample/SampleConditionTagger.svelte';
	import { FEATURES } from '$lib/features';
	import { Alert } from '$lib/components/primitives';
	import { extractLegacyReviewBboxes, extractPrimaryBboxes, mergeUniqueBboxes, parseBboxCollection, proposalColor } from '$lib/components/sample/bbox-helpers';

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
	// Session-local list of samples the reviewer pressed → on. Without
	// this the backend's deterministic per-user order serves the same top
	// candidate again and the queue gets stuck on a single sample. Reset
	// when filters change so changing the slice gives a fresh queue.
	let skippedIds = $state<string[]>([]);
	let lastLoadedReviewKey = $state<string | null>(null);
	let lastSampleId = $state<string | null>(null);
	let reviewImageAsset = $state<ReviewImageAsset>('image');

	// True when the current sample is a piece-condition crop (collected by the
	// sorter's condition_collector). In that case we render the tagger chip UI
	// alongside the existing card so a human can override any auto-label.
	let isConditionSample = $derived.by<boolean>(() => {
		const payload = sample?.sample_payload as { sample?: { capture_scope?: unknown } } | null;
		return payload?.sample?.capture_scope === 'condition';
	});

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
		const proposals = mergeUniqueBboxes(primaryBboxes, candidateBboxes);
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

	// Admin-only teacher rerun panel. Lets the reviewer try a different model on the
	// currently displayed sample without leaving the queue. UX is one button per model
	// (see TeacherRerunButtons) — turned out faster than a dropdown + Run for the
	// click-through review flow. Preferred-model still highlights the user's saved
	// default so the eye lands there first.
	onMount(() => {
		void loadNext();
	});

	function handleTeacherRerunResult(updated: SampleDetail) {
		sample = updated;
		// Detection was overwritten and review_status reset on the backend, so the local
		// review history no longer applies to these boxes — clear so the action pad
		// shows a fresh slate.
		reviews = [];
		currentDecision = null;
		lastLoadedReviewKey = null;
	}

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

	// Carry the samples-list sidebar filter through the review session so the queue only
	// serves the slice the reviewer chose (e.g. "C-Channel 4, last 24h"). The params live
	// in the URL — a refresh keeps the filter, navigating directly to /review without
	// query string opens the full queue as before.
	const queueFilters = $derived.by(() => {
		const sp = page.url.searchParams;
		const params: Record<string, string> = {};
		for (const key of ['scope', 'machine_id', 'source_role', 'capture_reason', 'kind', 'review_status', 'my_review', 'max_age_hours']) {
			const value = sp.get(key);
			if (value) params[key] = value;
		}
		return params;
	});
	const activeFilterChips = $derived(Object.entries(queueFilters));

	// Re-slicing the queue invalidates the skip set — a sample I skipped
	// inside "kind=regular" might be exactly what I want to see in
	// "kind=condition". Compare by string so the effect only fires when
	// the filter shape actually changes.
	let lastQueueFiltersKey = $state<string | null>(null);
	$effect(() => {
		const key = JSON.stringify(queueFilters);
		if (lastQueueFiltersKey !== null && key !== lastQueueFiltersKey) {
			skippedIds = [];
		}
		lastQueueFiltersKey = key;
	});

	const currentKind = $derived(queueFilters.kind ?? '');

	function setKind(next: '' | 'regular' | 'condition') {
		const url = new URL(page.url);
		if (next) url.searchParams.set('kind', next);
		else url.searchParams.delete('kind');
		void goto(`${url.pathname}${url.search ? url.search : ''}`, {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
	}

	async function loadNext() {
		loading = true;
		error = null;
		feedback = null;
		try {
			const next = await api.getNextReview(queueFilters, skippedIds);
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
			const submittedId = sample.id;
			const review = await api.submitReview(submittedId, decision);
			// In override mode (?review_status=conflict, ?my_review=...) the backend
			// drops the "already reviewed" gate, so without this push the same sample
			// would come back top-of-queue after the vote (md5 order is deterministic
			// per viewer) and arrow keys would feel like a no-op. In default mode the
			// backend already excludes own reviews — pushing here is redundant but
			// harmless and keeps the two paths symmetrical.
			if (!skippedIds.includes(submittedId)) {
				skippedIds = [...skippedIds, submittedId];
			}
			if (reviewHistory[reviewHistory.length - 1] !== submittedId) {
				reviewHistory = [...reviewHistory, submittedId];
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
		// Record the skip so the backend doesn't immediately hand it back
		// (its order is md5-deterministic per viewer), and so ← lets the
		// reviewer return to the skipped sample if they change their mind.
		if (sample) {
			const id = sample.id;
			if (!skippedIds.includes(id)) skippedIds = [...skippedIds, id];
			if (reviewHistory[reviewHistory.length - 1] !== id) {
				reviewHistory = [...reviewHistory, id];
			}
		}
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
		if (!FEATURES.ANNOTATION_EDITING) return;
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

		if (FEATURES.ANNOTATION_EDITING && event.key.toLowerCase() === 'd') {
			event.preventDefault();
			toggleAnnotateMode();
			return;
		}

		if (FEATURES.ANNOTATION_EDITING && event.key === 'Escape' && annotateMode) {
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
			Arrow up accepts, arrow down rejects, arrow right skips, arrow left goes back{#if FEATURES.ANNOTATION_EDITING}, and <kbd class="border border-border bg-bg px-1.5 py-0.5 text-[11px] font-semibold text-text">D</kbd> toggles annotation{/if}.
		</p>
		{#if activeFilterChips.length > 0}
			<div class="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
				<span class="text-text-muted">Scoped to:</span>
				{#each activeFilterChips as [key, value] (key)}
					<span class="border border-border bg-bg px-1.5 py-0.5 text-text-muted">
						{key}=<span class="text-text">{value}</span>
					</span>
				{/each}
				<a href="/review" class="text-primary hover:underline">Clear</a>
			</div>
		{/if}
	</div>
	<!-- Kind switcher — flips the queue between regular detection samples and
	     piece-condition crops without leaving the review page. -->
	<div class="flex border border-border bg-surface text-xs">
		{#each [
			{ value: '', label: 'All' },
			{ value: 'regular', label: 'Regular' },
			{ value: 'condition', label: 'Condition' }
		] as opt}
			<button
				type="button"
				class="border-l border-border px-3 py-1.5 first:border-l-0 {currentKind === opt.value ? 'bg-primary text-white' : 'text-text hover:bg-bg'}"
				onclick={() => setKind(opt.value as '' | 'regular' | 'condition')}
			>
				{opt.label}
			</button>
		{/each}
	</div>
</div>

{#if loading}
	<Spinner />
{:else if empty}
	<div class="border border-border bg-surface p-10 text-center">
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
					class="px-3 py-1.5 text-xs font-medium transition-colors {annotateMode ? 'text-text-muted hover:text-text' : 'bg-surface text-text'}"
				>
					Review
				</button>
				<button
					type="button"
					onclick={toggleAnnotateMode}
					class="px-3 py-1.5 text-xs font-medium transition-colors {annotateMode ? 'bg-surface text-text' : 'text-text-muted hover:text-text'}"
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
			<div class="border border-border bg-surface p-4">
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

			<SampleConditionCard samplePayload={sample.sample_payload} />

			{#if isConditionSample}
				<SampleConditionTagger
					sampleId={sample.id}
					samplePayload={sample.sample_payload}
					onSaved={(analysis) => {
						// Splice the freshly-saved analysis into the local sample so the
						// adjacent SampleConditionCard reflects the new label without
						// waiting for a refetch.
						if (sample) {
							const payload = (sample.sample_payload as Record<string, unknown> | null) ?? {};
							const analyses = Array.isArray(payload.analyses) ? (payload.analyses as Record<string, unknown>[]) : [];
							const filtered = analyses.filter((a) => (a as { analysis_id?: string }).analysis_id !== 'cond_primary');
							filtered.push(analysis);
							sample = { ...sample, sample_payload: { ...payload, analyses: filtered } };
						}
					}}
				/>
			{/if}

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

			{#if auth.isAdmin}
				<TeacherRerunButtons
					sampleId={sample.id}
					onResult={handleTeacherRerunResult}
					preferredModelId={auth.user?.preferred_teacher_model ?? null}
					dense
				/>
			{/if}

			<ReviewHeuristics />

			{#if annotateMode}
				<ReviewAnnotatorPanel {annotatorApi} />
			{/if}

		</div>
	</div>
{/if}
