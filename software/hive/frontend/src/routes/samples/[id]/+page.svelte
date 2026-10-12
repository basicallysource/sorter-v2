<script lang="ts">
	import { sentence } from '$lib/text';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		api,
		type SampleClassificationPayload,
		type SampleDetail,
		type SampleReview,
		type SampleSwatchRun,
		type SavedSampleAnnotation
	} from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import SampleAnnotator, { type SeedBox } from '$lib/components/SampleAnnotator.svelte';
	import { FEATURES } from '$lib/features';
	import TeacherRerunButtons from '$lib/components/teacher/TeacherRerunButtons.svelte';
	import SampleClassificationCard from '$lib/components/SampleClassificationCard.svelte';
	import { AnnotatorApi } from '$lib/components/annotator-api.svelte';
	import { auth } from '$lib/auth.svelte';
	import SampleImageViewer from '$lib/components/sample/SampleImageViewer.svelte';
	import SampleAnnotatorPanel from '$lib/components/sample/SampleAnnotatorPanel.svelte';
	import SampleConditionCard from '$lib/components/sample/SampleConditionCard.svelte';
	import SampleDetailsSidebar from '$lib/components/sample/SampleDetailsSidebar.svelte';
	import SampleSwatchesCard from '$lib/components/sample/SampleSwatchesCard.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Check from '@lucide/svelte/icons/check';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Columns2 from '@lucide/svelte/icons/columns-2';
	import ImageOff from '@lucide/svelte/icons/image-off';
	import ScanSearch from '@lucide/svelte/icons/scan-search';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';
	import { extractLegacyReviewBboxes, extractPrimaryBboxes, mergeUniqueBboxes, parseBboxCollection, proposalColor } from '$lib/components/sample/bbox-helpers';
	import { readSampleFilters, sampleFiltersQuery, sampleQueue } from '$lib/sampleListContext';
	import { queueFor, queueKeydown, type QueueSteps, type ReviewQueue } from '$lib/reviewQueue.svelte';
	import { formatDateTime, relativeTime } from '$lib/time';

	const annotatorApi = new AnnotatorApi();

	let sample = $state<SampleDetail | null>(null);
	let reviews = $state<SampleReview[]>([]);
	let loading = $state(true);
	// The colour reference palette's readings on this frame, newest run first.
	let swatchRuns = $state<SampleSwatchRun[]>([]);
	let swatchRunId = $state<string | undefined>(undefined);
	let showSwatches = $state(true);
	const swatchRun = $derived(swatchRuns.find((r) => r.id === swatchRunId) ?? swatchRuns[0] ?? null);
	let showDeleteModal = $state(false);

	// Image view toggle — persisted via ?view= query param
	type ViewMode = 'image' | 'full_frame' | 'channel_crop' | 'overlay' | 'annotate';
	type ImageRenderAsset = 'image' | 'full_frame';
	const validViews: ViewMode[] = ['image', 'full_frame', 'channel_crop', 'overlay', 'annotate'];

	function readViewFromUrl(): ViewMode {
		const v = page.url.searchParams.get('view');
		// If a stale URL still references the annotate view but the feature is
		// gated off, fall back to the default image view instead of mounting
		// the half-baked annotator behind no toggle.
		if (v === 'annotate' && !FEATURES.ANNOTATION_EDITING) return 'image';
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
	let imageNaturalWidth = $state(0);
	let imageNaturalHeight = $state(0);
	let imageRenderAsset = $state<ImageRenderAsset>('image');
	let lastLoadedSampleId = $state<string | null>(null);

	const sampleId = $derived(page.params.id);

	// The list this sample was opened from: the filters in the URL, and the queue
	// the grid already loaded for them (lib/sampleListContext). Previous / next
	// and the arrow keys step through that same list.
	const listContext = $derived(readSampleFilters(page.url.searchParams));

	// Or, with ?teacher_job=<id>, the items of that teacher job, so an admin can
	// step through a backfill from here.
	const teacherJobId = $derived(page.url.searchParams.get('teacher_job'));
	const teacherJobItemsStatus = $derived(page.url.searchParams.get('teacher_job_items_status') ?? 'all');

	function teacherJobQueue(jobId: string, status: string): ReviewQueue<{ id: string }> {
		return queueFor<{ id: string }>('teacher-job', `${jobId}:${status}`, {
			key: (it) => it.id,
			fetch: async (cursor) => {
				const pageNum = cursor ? Number(cursor) : 1;
				const job = await api.getTeacherJob(jobId, {
					items_page: pageNum,
					items_page_size: 50,
					items_status: status === 'all' ? undefined : status
				});
				return {
					items: job.items.map((i) => ({ id: i.sample_id })),
					next_cursor: pageNum < job.items_pages ? String(pageNum + 1) : null
				};
			}
		});
	}

	const navQueue = $derived<QueueSteps>(
		teacherJobId ? teacherJobQueue(teacherJobId, teacherJobItemsStatus) : sampleQueue(listContext)
	);

	const listBackHref = $derived(
		teacherJobId ? `/admin/teacher-jobs/${teacherJobId}` : `/samples${sampleFiltersQuery(page.url.searchParams)}`
	);

	// Make sure this sample is in the loaded list (a link opened on its own
	// loads pages until it finds it).
	$effect(() => {
		if (sampleId) void navQueue.find(sampleId);
	});

	const navIndex = $derived(sampleId ? navQueue.indexOf(sampleId) : -1);
	const prevSampleId = $derived(navIndex > 0 ? navQueue.items[navIndex - 1].id : null);
	const hasNext = $derived(navIndex >= 0 && (navIndex + 1 < navQueue.items.length || navQueue.hasMore));
	const positionLabel = $derived(
		navIndex < 0 ? null : `${navIndex + 1} of ${navQueue.items.length.toLocaleString()}${navQueue.hasMore ? '+' : ''}`
	);

	function navigateTo(targetId: string | null) {
		if (!targetId) return;
		// The filters (or the teacher job) and the view stay in the URL.
		void goto(`/samples/${targetId}${page.url.search}`, { noScroll: true, keepFocus: true });
	}

	async function navigateNext() {
		if (!sampleId) return;
		const next = await navQueue.after(sampleId);
		if (next) navigateTo(next.id);
	}

	function onWindowKeyDown(e: KeyboardEvent) {
		if (showDeleteModal) return;
		if (activeView === 'annotate') return;
		queueKeydown(e, { prev: () => navigateTo(prevSampleId), next: () => void navigateNext() });
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
		in_review: 'Needs more reviews',
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
		const proposals = mergeUniqueBboxes(bboxes, candidateBboxes);
		return proposals.length > 0 ? proposals : legacyReviewBboxes;
	});

	const viewOptions = $derived<{ value: ViewMode; label: string }[]>([
		{ value: 'image', label: 'Image' },
		...(sample?.has_full_frame ? [{ value: 'full_frame' as const, label: 'Full frame' }] : []),
		...(sample?.has_channel_geometry ? [{ value: 'channel_crop' as const, label: 'Channel crop' }] : []),
		...(sample?.has_overlay ? [{ value: 'overlay' as const, label: 'Overlay' }] : []),
		...(FEATURES.ANNOTATION_EDITING ? [{ value: 'annotate' as const, label: 'Annotate' }] : [])
	]);

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
			void loadSwatchRuns(s);
			const urlView = readViewFromUrl();
			activeView = urlView;
			annotatorMounted = urlView === 'annotate';
		} catch {
			sample = null;
		} finally {
			loading = false;
		}
	}

	async function loadSwatchRuns(s: SampleDetail) {
		swatchRuns = [];
		swatchRunId = undefined;
		if (!s.has_full_frame) return;
		try {
			const { runs } = await api.getSampleSwatchRuns(s.id);
			if (sample?.id === s.id) swatchRuns = runs;
		} catch {
			// Readings are extra: the page works without them.
		}
	}

	// Reviewers can vote (or change their vote) directly from the detail
	// page — useful for revisiting conflict samples without going back
	// through the queue. The POST endpoint is an upsert keyed by
	// (sample_id, reviewer_id) so resubmitting just overwrites.
	let voteSubmitting = $state(false);
	let voteError = $state<string | null>(null);

	async function submitVote(decision: 'accept' | 'reject') {
		if (!sample || voteSubmitting) return;
		voteSubmitting = true;
		voteError = null;
		try {
			await api.submitReview(sample.id, decision);
			await loadSample(sample.id);
		} catch (e) {
			voteError = e instanceof Error ? e.message : 'Vote failed.';
		} finally {
			voteSubmitting = false;
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

	function handleTeacherRerunResult(updated: SampleDetail) {
		sample = updated;
		// The teacher reset review state on the backend — drop local history so the panel
		// reflects the fresh slate.
		reviews = [];
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
		if (val === null || val === undefined) return '-';
		if (typeof val === 'boolean') return val ? 'Yes' : 'No';
		if (typeof val === 'number') return Number.isInteger(val) ? String(val) : val.toFixed(4);
		if (typeof val === 'string') return val;
		return JSON.stringify(val);
	}

	function formatDate(d: string): string {
		return new Date(d).toLocaleString('en-US', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	function shortId(id: string): string {
		if (id.length > 16) return id.slice(0, 8) + '...' + id.slice(-6);
		return id;
	}
</script>

<svelte:head>
	<title>Sample - Hive</title>
</svelte:head>

<svelte:window onkeydown={onWindowKeyDown} />

<div>
	<Button href={listBackHref} size="sm" variant="ghost" icon={ArrowLeft}>{teacherJobId ? 'Teacher job' : 'Samples'}</Button>
</div>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if !sample}
	<Panel><EmptyState icon={ImageOff} title="Sample not found">It may have been deleted, or the link is wrong.</EmptyState></Panel>
{:else}
	<PageHeader title={`Sample ${shortId(sample.local_sample_id)}`}>
		<div class="mt-1.5 flex flex-wrap items-center gap-2">
			<Badge tone={statusVariant[sample.review_status] ?? 'neutral'}>{statusLabel[sample.review_status] ?? sentence(sample.review_status)}</Badge>
			{#if sample.review_count > 0}
				<span class="num text-sm text-ink-muted">{sample.review_count} review{sample.review_count !== 1 ? 's' : ''}</span>
			{/if}
			{#if sample.captured_at ?? sample.uploaded_at}
				{@const at = (sample.captured_at ?? sample.uploaded_at)!}
				<span class="num text-sm text-ink-muted" title={at}
					>{sample.captured_at ? 'captured' : 'uploaded'} {formatDateTime(at)} ({relativeTime(at)})</span
				>
			{/if}
		</div>
		{#snippet actions()}
			<div class="flex items-center gap-1" title="The arrow keys step through the samples too">
				<Button icon={ChevronLeft} label="Previous sample" disabled={!prevSampleId} onclick={() => navigateTo(prevSampleId)} />
				{#if positionLabel}<span class="num px-1 text-sm text-ink-muted">{positionLabel}</span>{/if}
				<Button icon={ChevronRight} label="Next sample" disabled={!hasNext} onclick={() => void navigateNext()} />
			</div>
			<Button
				href={`/samples/${sample!.id}/similar`}
				icon={ScanSearch}
				title="Samples that look like this one, by perceptual hash: bursts of near-identical frames, or a batch under the same bad light"
				>Find similar</Button
			>
			{#if auth.isAdmin}
				<Button href={`/samples/${sample!.id}/compare`} icon={Columns2} title="Every teacher model on this sample, side by side"
					>Compare models</Button
				>
				<Button icon={Trash2} onclick={() => (showDeleteModal = true)}>Delete</Button>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="grid gap-(--gap-panels) lg:grid-cols-[1fr_340px]">
		<div class="flex min-w-0 flex-col gap-3">
			<div class="flex flex-wrap items-center justify-between gap-3">
				{#if viewOptions.length > 1}
					<SegmentedControl label="View" size="sm" value={activeView} options={viewOptions} onchange={setView} />
				{/if}
				<div class="flex items-center gap-4">
					{#if activeView === 'image' && proposalBoxes.length > 0}
						<Checkbox bind:checked={showBboxOverlay}>Boxes</Checkbox>
					{/if}
					{#if swatchRun && (activeView === 'image' || activeView === 'full_frame')}
						<Checkbox bind:checked={showSwatches}>Swatches</Checkbox>
					{/if}
				</div>
			</div>

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
					swatchRun={showSwatches ? swatchRun : null}
				/>
			{/if}

			{#if usingFullFrameFallback}
				<Alert>This shows the full frame, because this classification chamber sample's boxes are in full-frame coordinates.</Alert>
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
						{hasPersistedAnnotations}
						isActive={activeView === 'annotate'}
						externalApi={annotatorApi}
					/>
				</div>
			{/if}

			{#if detectionMessage && activeView !== 'annotate'}
				<p class="text-sm text-ink-muted">{detectionMessage}</p>
			{/if}
		</div>

		<div class="flex min-w-0 flex-col gap-(--gap-panels)">
			{#if activeView === 'annotate'}
				<SampleAnnotatorPanel {annotatorApi} />
			{/if}

			<!-- The same vote as the review page's, so a reviewer can change it from here. -->
			{#if auth.isReviewer}
				{@const myVote = sample.my_review_decision}
				<Panel title="Your review" flush>
					{#snippet actions()}
						{#if myVote}
							<Badge tone={myVote === 'accept' ? 'success' : 'danger'}>{myVote === 'accept' ? 'You accepted' : 'You rejected'}</Badge>
						{:else}
							<span class="text-sm text-ink-muted">Not voted</span>
						{/if}
					{/snippet}
					<div class="flex flex-col gap-3 px-(--pad-panel) pb-(--pad-panel)">
						<div class="grid grid-cols-2 gap-2">
							<Button
								variant="primary"
								icon={Check}
								loading={voteSubmitting}
								disabled={myVote === 'accept'}
								onclick={() => void submitVote('accept')}
								>{myVote === 'accept' ? 'Accepted' : myVote === 'reject' ? 'Accept instead' : 'Accept'}</Button
							>
							<Button icon={X} loading={voteSubmitting} disabled={myVote === 'reject'} onclick={() => void submitVote('reject')}
								>{myVote === 'reject' ? 'Rejected' : myVote === 'accept' ? 'Reject instead' : 'Reject'}</Button
							>
						</div>
						{#if voteError}<Alert tone="danger">{voteError}</Alert>{/if}
						<p class="num text-sm text-ink-muted">
							{sample.review_count} of 3 reviews: {sample.accepted_count} accepted, {sample.rejected_count} rejected
						</p>
					</div>
				</Panel>
			{/if}

			{#if sample.detection_algorithm || detectionFound !== undefined}
				<Panel title="Detection" flush>
					{#snippet actions()}
						{#if detectionFound !== undefined}
							<Badge tone={detectionFound ? 'success' : 'danger'} dot>{detectionFound ? 'Found' : 'Not found'}</Badge>
						{/if}
					{/snippet}
					<div class="px-(--pad-panel) pb-2">
						<KeyValue
							items={[
								...(sample.detection_algorithm ? [{ label: 'Algorithm', value: sample.detection_algorithm }] : []),
								...(sample.detection_count != null ? [{ label: 'Count', value: sample.detection_count }] : []),
								...(sample.detection_score != null ? [{ label: 'Score', value: sample.detection_score.toFixed(2) }] : []),
								...(proposalBoxes.length > 0 ? [{ label: 'Proposals', value: proposalBoxes.length }] : []),
								...(detectionOpenrouterModel ? [{ label: 'Model', value: detectionOpenrouterModel, mono: true }] : [])
							]}
						/>
					</div>
				</Panel>
			{/if}

			{#if swatchRuns.length > 0}
				<SampleSwatchesCard runs={swatchRuns} selectedId={swatchRun?.id} onselect={(id) => (swatchRunId = id)} />
			{/if}

			{#if auth.isAdmin}
				<TeacherRerunButtons
					sampleId={sample.id}
					onResult={handleTeacherRerunResult}
					preferredModelId={auth.user?.preferred_teacher_model ?? null}
				/>
			{/if}

			<SampleClassificationCard
				sampleId={sample.id}
				sourceRole={sample.source_role}
				captureReason={sample.capture_reason}
				extraMetadata={sample.extra_metadata}
				onSaved={handleClassificationSaved}
			/>

			<SampleConditionCard samplePayload={sample.sample_payload} />

			<SampleDetailsSidebar {sample} {reviews} {camera} {detectionScope} {pieceUuid} {runId} {extra} {extraKeys} {formatValue} {formatDate} {shortId} />
		</div>
	</div>

	<Modal open={showDeleteModal} title="Delete this sample?" size="sm" onclose={() => (showDeleteModal = false)}>
		<p class="text-sm text-ink">The sample, its pictures and its reviews go for good.</p>
		{#snippet footer()}
			<Button variant="ghost" onclick={() => (showDeleteModal = false)}>Cancel</Button>
			<Button variant="danger" onclick={handleDelete}>Delete</Button>
		{/snippet}
	</Modal>
{/if}
