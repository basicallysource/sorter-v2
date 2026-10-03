<script lang="ts">
	import { sentence } from '$lib/text';
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

	// List context (filters + page size) carried in the URL so reload preserves the
	// browsing context. Lets us walk to prev/next neighbours without losing filters.
	const listContext = $derived(readSampleListContext(page.url.searchParams));
	const listContextKey = $derived(sampleListContextKey(listContext));

	// Alternative navigation source: when the URL carries ?teacher_job=<id>, prev/next
	// walks through that job's items (paginated 50/page) instead of the global samples
	// roster. Lets the admin step through a backfill from inside the sample detail view.
	const teacherJobId = $derived(page.url.searchParams.get('teacher_job'));
	const teacherJobItemsStatus = $derived(
		page.url.searchParams.get('teacher_job_items_status') ?? 'all'
	);
	const teacherJobNavKey = $derived(
		teacherJobId ? `job:${teacherJobId}:${teacherJobItemsStatus}` : null
	);

	const listBackHref = $derived(
		teacherJobId
			? `/admin/teacher-jobs/${teacherJobId}`
			: `/samples${sampleListContextQuery(page.url.searchParams)}`
	);

	// Single key that flushes the neighbor cache when the source changes (filter on
	// samples list, OR switch to a different teacher job).
	const navSourceKey = $derived(teacherJobNavKey ?? listContextKey);
	const navPageSize = $derived(teacherJobId ? 50 : listContext.page_size);

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
		const absoluteIndex = (loc.pageNum - 1) * navPageSize + loc.idx + 1;
		return `${absoluteIndex} of ${neighborMeta.total}`;
	});

	$effect(() => {
		if (navSourceKey !== lastNeighborKey) {
			lastNeighborKey = navSourceKey;
			neighborPages = new SvelteMap();
			neighborMeta = null;
		}
	});

	$effect(() => {
		if (!sampleId) return;
		if (teacherJobId) {
			const start = Number(page.url.searchParams.get('teacher_job_items_page') ?? '1');
			void ensureNeighborPage(Math.max(1, start));
		} else {
			void ensureNeighborPage(listContext.page);
		}
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
		const sourceAtRequest = navSourceKey;
		try {
			if (teacherJobId) {
				const result = await api.getTeacherJob(teacherJobId, {
					items_page: pageNum,
					items_page_size: navPageSize,
					items_status: teacherJobItemsStatus === 'all' ? undefined : teacherJobItemsStatus
				});
				if (navSourceKey !== sourceAtRequest) return;
				neighborPages.set(pageNum, result.items.map((i) => i.sample_id));
				neighborMeta = { pages: result.items_pages, total: result.items_total };
			} else {
				const result = await api.getSamples({
					...sampleListFilterParams(listContext),
					page: pageNum,
					page_size: listContext.page_size
				});
				if (navSourceKey !== sourceAtRequest) return;
				neighborPages.set(pageNum, result.items.map((s) => s.id));
				neighborMeta = { pages: result.pages, total: result.total };
			}
		} catch {
			// ignore — neighbor info is best-effort
		}
	}

	function navigateToNeighbor(targetId: string | null) {
		if (!targetId) return;
		// Default page based on source: when navigating via teacher_job, use the
		// teacher_job_items_page param so the back-link lands on the right job page.
		const defaultPage = teacherJobId
			? Number(page.url.searchParams.get('teacher_job_items_page') ?? '1')
			: listContext.page;
		let targetPage = defaultPage;
		for (const [pageNum, ids] of neighborPages.entries()) {
			if (ids.includes(targetId)) {
				targetPage = pageNum;
				break;
			}
		}
		const sp = new URLSearchParams(page.url.searchParams);
		const pageKey = teacherJobId ? 'teacher_job_items_page' : 'page';
		if (targetPage <= 1) sp.delete(pageKey);
		else sp.set(pageKey, String(targetPage));
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
			const urlView = readViewFromUrl();
			activeView = urlView;
			annotatorMounted = urlView === 'annotate';
		} catch {
			sample = null;
		} finally {
			loading = false;
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
		</div>
		{#snippet actions()}
			<div class="flex items-center gap-1" title="The arrow keys step through the samples too">
				<Button icon={ChevronLeft} label="Previous sample" disabled={!prevSampleId} onclick={() => navigateToNeighbor(prevSampleId)} />
				{#if positionLabel}<span class="num px-1 text-sm text-ink-muted">{positionLabel}</span>{/if}
				<Button icon={ChevronRight} label="Next sample" disabled={!nextSampleId} onclick={() => navigateToNeighbor(nextSampleId)} />
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
				{#if activeView === 'image' && proposalBoxes.length > 0}
					<Checkbox bind:checked={showBboxOverlay}>Boxes</Checkbox>
				{/if}
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
