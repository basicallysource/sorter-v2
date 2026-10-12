<script lang="ts">
	import { sentence } from '$lib/text';
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
	import SampleAnnotatorPanel from '$lib/components/sample/SampleAnnotatorPanel.svelte';
	import ReviewHeuristics from '$lib/components/review/ReviewHeuristics.svelte';
	import TeacherRerunButtons from '$lib/components/teacher/TeacherRerunButtons.svelte';
	import SampleConditionCard from '$lib/components/sample/SampleConditionCard.svelte';
	import SampleConditionTagger from '$lib/components/sample/SampleConditionTagger.svelte';
	import { FEATURES } from '$lib/features';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import { readSampleFilters, reviewQueue } from '$lib/sampleListContext';
	import { formatDateTime, relativeTime } from '$lib/time';
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
	// The queue this page steps through: the samples list's filters from the
	// URL (lib/sampleListContext), and with no review state chosen, the fresh
	// work: samples I have not reviewed that still need reviews.
	const filters = $derived(readSampleFilters(page.url.searchParams));
	const queue = $derived(reviewQueue(filters));
	const position = $derived(sample ? queue.indexOf(sample.id) : -1);

	// A new filter is a new queue: start at its first sample.
	$effect(() => {
		const q = queue;
		void q.start().then(() => {
			if (q === queue) void showAt(q, 0);
		});
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

	const activeFilterChips = $derived(
		[
			...Object.entries(filters).filter(([k, v]) => k !== 'machine_ids' && typeof v === 'string' && v),
			...(filters.machine_ids.length > 0 ? [['machine', `${filters.machine_ids.length}`]] : [])
		] as [string, string][]
	);

	const currentKind = $derived(filters.kind ?? '');

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

	// Show the queue's i-th sample, loading the next page when it is past the
	// end of what is loaded; the empty state at the end of the queue.
	async function showAt(q: typeof queue, i: number) {
		while (i >= q.items.length && q.hasMore) {
			if (!(await q.loadMore()) && (q.error || !q.hasMore)) break;
		}
		if (q !== queue) return; // the filters changed meanwhile
		const target = q.items[i];
		annotateMode = false;
		if (!target) {
			sample = null;
			reviews = [];
			currentDecision = null;
			empty = true;
			error = q.error;
			loading = false;
			return;
		}
		await loadSample(target.id);
	}

	// Back to the sample before this one in the queue.
	async function goBack() {
		if (!sample || submitting || loading || position <= 0) return;
		const classificationOk = await savePendingClassificationIfNeeded();
		if (!classificationOk) return;
		const annotationsOk = await savePendingAnnotationsIfNeeded();
		if (!annotationsOk) return;
		await showAt(queue, position - 1);
	}

	async function goNext() {
		await showAt(queue, position + 1);
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
			currentDecision = review.decision;
			feedback =
				review.decision === 'accept'
					? 'Accepted. Loading the next sample...'
					: 'Rejected. Loading the next sample...';
			await goNext();
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
		await goNext();
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
		if (!value) return '-';
		return new Date(value).toLocaleString('en-US', {
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

<PageHeader
	title="Review"
	description={`Up accepts, down rejects, right skips and left goes back${FEATURES.ANNOTATION_EDITING ? '; D annotates' : ''}.`}
>
	{#if activeFilterChips.length > 0}
		<div class="flex flex-wrap items-center gap-1.5">
			<span class="text-sm text-ink-muted">Only</span>
			{#each activeFilterChips as [key, value] (key)}
				<Badge>{key} <span class="font-mono text-ink">{value}</span></Badge>
			{/each}
			<Button size="sm" variant="ghost" href="/review">Clear</Button>
		</div>
	{/if}
	{#snippet actions()}
		<SegmentedControl
			label="Kind"
			size="sm"
			value={currentKind}
			options={[
				{ value: '', label: 'All' },
				{ value: 'regular', label: 'Detection' },
				{ value: 'condition', label: 'Condition' }
			]}
			onchange={(kind: string) => setKind(kind as '' | 'regular' | 'condition')}
		/>
	{/snippet}
</PageHeader>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if empty}
	<Panel><EmptyState icon={CircleCheck} title="Nothing left to review">Come back when the machines have uploaded more.</EmptyState></Panel>
{:else if sample}
	{#if error}<Alert tone="danger">{error}</Alert>{/if}
	{#if feedback}<Alert tone="success">{feedback}</Alert>{/if}

	<div class="grid gap-(--gap-panels) lg:grid-cols-[1fr_360px]">
		<div class="flex min-w-0 flex-col gap-3">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<SegmentedControl
					label="Mode"
					size="sm"
					value={annotateMode ? 'annotate' : 'review'}
					options={[
						{ value: 'review', label: 'Review' },
						{ value: 'annotate', label: 'Annotate' }
					]}
					onchange={(mode: string) => {
						if (mode === 'annotate' && !annotateMode) toggleAnnotateMode();
						else if (mode === 'review') annotateMode = false;
					}}
				/>
				{#if !annotateMode && proposalBoxes.length > 0}
					<Checkbox bind:checked={showBboxOverlay}>Boxes</Checkbox>
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
					{hasPersistedAnnotations}
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
				<Alert>This shows the full frame, because this classification chamber sample's boxes are in full-frame coordinates.</Alert>
			{/if}
		</div>

		<div class="flex min-w-0 flex-col gap-(--gap-panels)">
			<Panel flush>
				<div class="flex flex-wrap items-center gap-1.5 px-(--pad-panel) pt-4 pb-1">
					<Badge tone="info">{sentence(sample.review_status)}</Badge>
					{#if currentDecision}
						<Badge tone={currentDecision === 'accept' ? 'success' : 'danger'}>{currentDecision === 'accept' ? 'You accepted' : 'You rejected'}</Badge>
					{/if}
					{#if detectionFound !== null}
						<Badge tone={detectionFound ? 'success' : 'danger'} dot>{detectionFound ? 'Found' : 'Not found'}</Badge>
					{/if}
					{#if sample.source_role}<Badge>{sentence(sample.source_role)}</Badge>{/if}
				</div>
				<div class="px-(--pad-panel) pb-2">
					<KeyValue
						items={[
							{ label: 'Sample', value: shortId(sample.local_sample_id), mono: true },
							{
								label: 'Captured',
								value: sample.captured_at ? `${formatDateTime(sample.captured_at)} (${relativeTime(sample.captured_at)})` : '-'
							},
							{ label: 'Uploaded', value: formatDate(sample.uploaded_at) },
							...(sample.capture_reason ? [{ label: 'Reason', value: sample.capture_reason, mono: true }] : []),
							...(camera ? [{ label: 'Camera', value: camera }] : []),
							...(detectionScope ? [{ label: 'Scope', value: detectionScope }] : []),
							...(sample.detection_algorithm ? [{ label: 'Detection', value: sample.detection_algorithm }] : []),
							...(sample.detection_score != null ? [{ label: 'Score', value: sample.detection_score.toFixed(2) }] : []),
							...(proposalBoxes.length > 0 ? [{ label: 'Proposals', value: proposalBoxes.length }] : [])
						]}
					/>
				</div>
			</Panel>

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
						// Splice the saved analysis into the local sample, so the condition
						// card beside it shows the new label without a refetch.
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
				reviewHistoryLength={Math.max(0, position)}
				onToggleAnnotate={toggleAnnotateMode}
				onExitAnnotate={() => (annotateMode = false)}
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
				/>
			{/if}

			<ReviewHeuristics />

			{#if annotateMode}
				<SampleAnnotatorPanel {annotatorApi} />
			{/if}
		</div>
	</div>
{/if}
