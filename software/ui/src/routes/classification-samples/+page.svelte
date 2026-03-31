<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { ChevronLeft, ChevronRight, RefreshCw, Search, SlidersHorizontal, X } from 'lucide-svelte';

	type SessionSummary = {
		session_id: string;
		session_name: string;
		created_at: number | null;
		processor: string;
		sample_count: number;
		completed_count: number;
		failed_count: number;
	};

	type ClassificationResultSummary = {
		provider?: string | null;
		status?: string | null;
		part_id?: string | null;
		item_name?: string | null;
		color_name?: string | null;
		confidence?: number | null;
		selected_crop_url?: string | null;
	};

	type SampleSummary = {
		session_id: string;
		session_name: string;
		sample_id: string;
		source: string;
		source_role?: string | null;
		capture_reason?: string | null;
		detection_scope?: string | null;
		camera?: string | null;
		preferred_camera?: string | null;
		captured_at: number | null;
		processor: string;
		detection_algorithm?: string | null;
		detection_openrouter_model?: string | null;
		detection_bbox_count?: number | null;
		distill_status: 'completed' | 'failed' | 'pending' | 'skipped';
		distill_detections?: number | null;
		retest_count: number;
		review_status?: string | null;
		review_updated_at?: number | null;
		input_image_url?: string | null;
		overlay_image_url?: string | null;
		classification_result?: ClassificationResultSummary | null;
		detail_url?: string | null;
	};

	type FacetSession = {
		id: string;
		label: string;
		count: number;
	};

	type LibraryFacets = {
		sessions: FacetSession[];
		detection_scopes: string[];
		source_roles: string[];
		capture_reasons: string[];
		detection_algorithms: string[];
		classification_statuses: string[];
		review_statuses: string[];
	};

	type PaginationState = {
		page: number;
		page_size: number;
		page_count: number;
		total_count: number;
	};

	type WorkerStatus = {
		processor: string;
		pending_count: number;
		completed_count: number;
		failed_count: number;
		queue_depth: number;
		running: boolean;
		items_per_minute?: number | null;
		eta_seconds?: number | null;
		active_model?: string | null;
		active_scope?: string | null;
		last_task_status?: string | null;
	};

	type BulkClearResult = {
		distill_status: 'failed' | 'pending' | 'skipped';
		matched_count: number;
		deleted_count: number;
		blocked_count: number;
		error_count: number;
		removed_session_count: number;
	};

	type BulkRetryResult = {
		distill_status: 'failed' | 'skipped';
		matched_count: number;
		queued_count: number;
		skipped_count: number;
		error_count: number;
	};

	const SORT_OPTIONS = [
		{ id: 'captured_at', label: 'Captured Time' },
		{ id: 'classification_completed_at', label: 'Classification Time' },
		{ id: 'classification_confidence', label: 'Classification Confidence' },
		{ id: 'detections', label: 'Detection Count' },
		{ id: 'retests', label: 'Retest Count' },
		{ id: 'session', label: 'Session' },
		{ id: 'sample_id', label: 'Sample ID' }
	] as const;

	const PAGE_SIZE_OPTIONS = [24, 36, 60, 96];
	const DEFAULT_PAGE_SIZE = 36;
	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loadedRouteKey = $state('');
	let loading = $state(false);
	let errorMsg = $state<string | null>(null);
	let sessions = $state<SessionSummary[]>([]);
	let samples = $state<SampleSummary[]>([]);
	let facets = $state<LibraryFacets>({
		sessions: [],
		detection_scopes: [],
		source_roles: [],
		capture_reasons: [],
		detection_algorithms: [],
		classification_statuses: [],
		review_statuses: []
	});
	let pagination = $state<PaginationState>({
		page: 1,
		page_size: DEFAULT_PAGE_SIZE,
		page_count: 1,
		total_count: 0
	});
	let workerStatus = $state<WorkerStatus | null>(null);
	let bulkActionBusy = $state<'retry_failed' | 'failed' | 'pending' | 'skipped' | null>(null);
	let bulkActionMessage = $state<string | null>(null);
	let bulkActionTone = $state<'success' | 'error' | 'muted'>('muted');

	let searchDraft = $state('');
	let selectedSessionId = $state('all');
	let selectedScope = $state('all');
	let selectedSourceRole = $state('all');
	let selectedCaptureReason = $state('all');
	let selectedDetectionAlgorithm = $state('all');
	let selectedClassificationStatus = $state('all');
	let selectedHasClassificationResult = $state('all');
	let selectedReviewStatus = $state('all');
	let sortBy = $state<(typeof SORT_OPTIONS)[number]['id']>('captured_at');
	let sortDir = $state<'asc' | 'desc'>('desc');
	let pageSize = $state(DEFAULT_PAGE_SIZE);
	let currentPage = $state(1);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function assetUrl(path: string | null | undefined): string | null {
		if (typeof path !== 'string' || !path) return null;
		if (path.startsWith('http://') || path.startsWith('https://')) return path;
		return `${currentBackendBaseUrl()}${path}`;
	}

	function timeAgo(timestamp: number | null | undefined): string {
		if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return '';
		const seconds = Math.floor(Date.now() / 1000 - timestamp);
		if (seconds < 60) return 'just now';
		if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
		if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
		return `${Math.floor(seconds / 86400)}d ago`;
	}

	function formatDate(timestamp: number | null | undefined): string {
		if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return 'n/a';
		return new Date(timestamp * 1000).toLocaleString();
	}

	function humanize(value: string | null | undefined): string {
		if (typeof value !== "string" || !value) return 'n/a';
		const specialLabels: Record<string, string> = {
			classification_chamber: 'Classification Chamber',
			c_channel_2: 'C-Channel 2',
			c_channel_3: 'C-Channel 3',
			carousel: 'Carousel',
			channel_move_complete: 'Channel Move Complete',
			carousel_classic_trigger: 'Carousel Classic Trigger',
			live_aux_teacher_capture: 'Live Teacher Capture'
		};
		if (specialLabels[value]) return specialLabels[value];
		return value
			.split('_')
			.map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
			.join(' ');
	}

	function sourceDisplayLabel(sample: SampleSummary): string {
		return humanize(sample.source_role ?? sample.camera ?? sample.detection_scope ?? sample.source);
	}

	function modelShort(model: string | null | undefined): string {
		if (!model) return '';
		const parts = model.split('/');
		return parts[parts.length - 1] ?? model;
	}

	function activeFilterCount(): number {
		return [
			searchDraft.trim() ? 1 : 0,
			selectedSessionId !== 'all' ? 1 : 0,
			selectedScope !== 'all' ? 1 : 0,
			selectedSourceRole !== 'all' ? 1 : 0,
			selectedCaptureReason !== 'all' ? 1 : 0,
			selectedDetectionAlgorithm !== 'all' ? 1 : 0,
			selectedClassificationStatus !== 'all' ? 1 : 0,
			selectedHasClassificationResult !== 'all' ? 1 : 0,
			selectedReviewStatus !== 'all' ? 1 : 0,
			sortBy !== 'captured_at' ? 1 : 0,
			sortDir !== 'desc' ? 1 : 0,
			pageSize !== DEFAULT_PAGE_SIZE ? 1 : 0
		].reduce((sum, value) => sum + value, 0);
	}

	function hasActiveFilters(): boolean {
		return activeFilterCount() > 0;
	}

	function clearFilters() {
		searchDraft = '';
		selectedSessionId = 'all';
		selectedScope = 'all';
		selectedSourceRole = 'all';
		selectedCaptureReason = 'all';
		selectedDetectionAlgorithm = 'all';
		selectedClassificationStatus = 'all';
		selectedHasClassificationResult = 'all';
		selectedReviewStatus = 'all';
		sortBy = 'captured_at';
		sortDir = 'desc';
		pageSize = DEFAULT_PAGE_SIZE;
		currentPage = 1;
		void navigateToCurrentFilters();
	}

	function buildQueryParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('page', String(currentPage));
		params.set('page_size', String(pageSize));
		params.set('sort_by', sortBy);
		params.set('sort_dir', sortDir);
		if (searchDraft.trim()) params.set('search', searchDraft.trim());
		if (selectedSessionId !== 'all') params.set('session_id', selectedSessionId);
		if (selectedScope !== 'all') params.set('detection_scope', selectedScope);
		if (selectedSourceRole !== 'all') params.set('source_role', selectedSourceRole);
		if (selectedCaptureReason !== 'all') params.set('capture_reason', selectedCaptureReason);
		if (selectedDetectionAlgorithm !== 'all') params.set('detection_algorithm', selectedDetectionAlgorithm);
		if (selectedClassificationStatus !== 'all') {
			params.set('classification_status', selectedClassificationStatus);
		}
		if (selectedHasClassificationResult === 'with') {
			params.set('has_classification_result', 'true');
		} else if (selectedHasClassificationResult === 'without') {
			params.set('has_classification_result', 'false');
		}
		if (selectedReviewStatus !== 'all') {
			params.set('review_status', selectedReviewStatus);
		}
		return params;
	}

	function buildRouteUrl(): string {
		const params = buildQueryParams();
		const query = params.toString();
		return query ? `${page.url.pathname}?${query}` : page.url.pathname;
	}

	function buildLibraryUrl(): string {
		const params = buildQueryParams();
		return `${currentBackendBaseUrl()}/api/classification/training/library?${params.toString()}`;
	}

	function buildBulkClearUrl(status: 'failed' | 'pending' | 'skipped'): string {
		const params = buildQueryParams();
		params.set('distill_status', status);
		return `${currentBackendBaseUrl()}/api/classification/training/library/clear?${params.toString()}`;
	}

	function buildBulkRetryUrl(status: 'failed' | 'skipped'): string {
		const params = buildQueryParams();
		params.set('distill_status', status);
		return `${currentBackendBaseUrl()}/api/classification/training/library/retry?${params.toString()}`;
	}

	async function navigateToCurrentFilters() {
		const nextUrl = buildRouteUrl();
		const currentUrl = `${page.url.pathname}${page.url.search}`;
		if (nextUrl === currentUrl) {
			void loadLibrary();
			return;
		}
		await goto(nextUrl, {
			keepFocus: true,
			noScroll: true,
			invalidateAll: false,
			replaceState: false
		});
	}

	function applyUrlState() {
		const params = page.url.searchParams;
		const sortCandidates = new Set(SORT_OPTIONS.map((option) => option.id));
		const parsedPageSize = Number(params.get('page_size') ?? DEFAULT_PAGE_SIZE);
		const parsedPage = Number(params.get('page') ?? 1);
		const hasClassificationResult = params.get('has_classification_result');

		searchDraft = params.get('search')?.trim() ?? '';
		selectedSessionId = params.get('session_id') ?? 'all';
		selectedScope = params.get('detection_scope') ?? 'all';
		selectedSourceRole = params.get('source_role') ?? 'all';
		selectedCaptureReason = params.get('capture_reason') ?? 'all';
		selectedDetectionAlgorithm = params.get('detection_algorithm') ?? 'all';
		selectedClassificationStatus = params.get('classification_status') ?? 'all';
		selectedHasClassificationResult =
			hasClassificationResult === 'true'
				? 'with'
				: hasClassificationResult === 'false'
					? 'without'
					: 'all';
		selectedReviewStatus = params.get('review_status') ?? 'all';
		sortBy = sortCandidates.has((params.get('sort_by') ?? '') as (typeof SORT_OPTIONS)[number]['id'])
			? ((params.get('sort_by') ?? 'captured_at') as (typeof SORT_OPTIONS)[number]['id'])
			: 'captured_at';
		sortDir = params.get('sort_dir') === 'asc' ? 'asc' : 'desc';
		pageSize =
			Number.isFinite(parsedPageSize) && PAGE_SIZE_OPTIONS.includes(parsedPageSize)
				? parsedPageSize
				: DEFAULT_PAGE_SIZE;
		currentPage = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1;
	}

	function formatRate(itemsPerMinute: number | null | undefined): string {
		if (typeof itemsPerMinute !== 'number' || !Number.isFinite(itemsPerMinute) || itemsPerMinute <= 0) {
			return 'warming up';
		}
		return `${itemsPerMinute.toFixed(itemsPerMinute >= 10 ? 0 : 1)}/min`;
	}

	function formatEta(seconds: number | null | undefined): string {
		if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) {
			return 'calculating';
		}
		if (seconds < 60) return `${Math.round(seconds)}s`;
		if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
		return `${(seconds / 3600).toFixed(1)}h`;
	}

	function bulkClearConfirmation(status: 'failed' | 'pending' | 'skipped'): string {
		const scopeLabel = hasActiveFilters()
			? 'matching the current filters'
			: 'in the current sample library';
		if (status === 'pending') {
			return `Delete all pending samples ${scopeLabel}? Running distill jobs will be skipped. This cannot be undone.`;
		}
		return `Delete all ${status} samples ${scopeLabel}? This cannot be undone.`;
	}

	function bulkRetryConfirmation(status: 'failed' | 'skipped'): string {
		const scopeLabel = hasActiveFilters()
			? 'matching the current filters'
			: 'in the current sample library';
		return `Retry all ${status} samples ${scopeLabel}?`;
	}

	function formatBulkClearMessage(result: BulkClearResult): string {
		if (result.matched_count <= 0) {
			return `No ${result.distill_status} samples matched the current filters.`;
		}
		const parts = [`Deleted ${result.deleted_count} ${result.distill_status} sample${result.deleted_count === 1 ? '' : 's'}`];
		if (result.blocked_count > 0) {
			parts.push(`${result.blocked_count} running sample${result.blocked_count === 1 ? ' was' : 's were'} skipped`);
		}
		if (result.error_count > 0) {
			parts.push(`${result.error_count} could not be removed`);
		}
		return `${parts.join('. ')}.`;
	}

	function formatBulkRetryMessage(result: BulkRetryResult): string {
		if (result.matched_count <= 0) {
			return `No ${result.distill_status} samples matched the current filters.`;
		}
		const parts = [
			`Queued ${result.queued_count} ${result.distill_status} sample${result.queued_count === 1 ? '' : 's'} for retry`
		];
		if (result.skipped_count > 0) {
			parts.push(`${result.skipped_count} skipped`);
		}
		if (result.error_count > 0) {
			parts.push(`${result.error_count} errored`);
		}
		return `${parts.join('. ')}.`;
	}

	async function clearSamplesByStatus(status: 'failed' | 'pending' | 'skipped') {
		if (loading || bulkActionBusy) return;
		if (!window.confirm(bulkClearConfirmation(status))) return;
		bulkActionBusy = status;
		bulkActionMessage = null;
		try {
			const res = await fetch(buildBulkClearUrl(status), { method: 'POST' });
			if (!res.ok) throw new Error(await res.text());
			const payload = (await res.json()) as BulkClearResult;
			bulkActionTone = payload.error_count > 0 ? 'error' : payload.matched_count > 0 ? 'success' : 'muted';
			bulkActionMessage = formatBulkClearMessage(payload);
			await loadLibrary();
		} catch (error: unknown) {
			bulkActionTone = 'error';
			bulkActionMessage =
				error instanceof Error && error.message ? error.message : `Failed to clear ${status} samples.`;
		} finally {
			bulkActionBusy = null;
		}
	}

	async function retrySamplesByStatus(status: 'failed' | 'skipped') {
		if (loading || bulkActionBusy) return;
		if (!window.confirm(bulkRetryConfirmation(status))) return;
		bulkActionBusy = status === 'failed' ? 'retry_failed' : null;
		bulkActionMessage = null;
		try {
			const res = await fetch(buildBulkRetryUrl(status), { method: 'POST' });
			if (!res.ok) throw new Error(await res.text());
			const payload = (await res.json()) as BulkRetryResult;
			bulkActionTone = payload.error_count > 0 ? 'error' : payload.matched_count > 0 ? 'success' : 'muted';
			bulkActionMessage = formatBulkRetryMessage(payload);
			await loadLibrary();
		} catch (error: unknown) {
			bulkActionTone = 'error';
			bulkActionMessage =
				error instanceof Error && error.message ? error.message : `Failed to retry ${status} samples.`;
		} finally {
			bulkActionBusy = null;
		}
	}

	async function loadLibrary() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(buildLibraryUrl());
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			sessions = Array.isArray(payload?.sessions) ? payload.sessions : [];
			samples = Array.isArray(payload?.samples) ? payload.samples : [];
			facets = {
				sessions: Array.isArray(payload?.facets?.sessions) ? payload.facets.sessions : [],
				detection_scopes: Array.isArray(payload?.facets?.detection_scopes) ? payload.facets.detection_scopes : [],
				source_roles: Array.isArray(payload?.facets?.source_roles) ? payload.facets.source_roles : [],
				capture_reasons: Array.isArray(payload?.facets?.capture_reasons) ? payload.facets.capture_reasons : [],
				detection_algorithms: Array.isArray(payload?.facets?.detection_algorithms)
					? payload.facets.detection_algorithms
					: [],
				classification_statuses: Array.isArray(payload?.facets?.classification_statuses)
					? payload.facets.classification_statuses
					: [],
				review_statuses: Array.isArray(payload?.facets?.review_statuses)
					? payload.facets.review_statuses
					: []
			};
			workerStatus =
				payload?.worker_status && typeof payload.worker_status === 'object'
					? (payload.worker_status as WorkerStatus)
					: null;
			pagination = {
				page:
					typeof payload?.pagination?.page === 'number' && payload.pagination.page > 0
						? payload.pagination.page
						: 1,
				page_size:
					typeof payload?.pagination?.page_size === 'number' && payload.pagination.page_size > 0
						? payload.pagination.page_size
						: pageSize,
				page_count:
					typeof payload?.pagination?.page_count === 'number' && payload.pagination.page_count > 0
						? payload.pagination.page_count
						: 1,
				total_count:
					typeof payload?.pagination?.total_count === 'number' && payload.pagination.total_count >= 0
						? payload.pagination.total_count
						: samples.length
			};
			currentPage = pagination.page;
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message ? error.message : 'Failed to load samples.';
		} finally {
			loading = false;
		}
	}

	function applyFilters() {
		currentPage = 1;
		void navigateToCurrentFilters();
	}

	function setPage(page: number) {
		currentPage = page;
		void navigateToCurrentFilters();
	}

	function previousPage() {
		if (currentPage <= 1 || loading) return;
		setPage(currentPage - 1);
	}

	function nextPage() {
		if (currentPage >= pagination.page_count || loading) return;
		setPage(currentPage + 1);
	}

	function paginationLabel(): string {
		if (pagination.total_count <= 0) return '0 results';
		const start = (pagination.page - 1) * pagination.page_size + 1;
		const end = Math.min(pagination.total_count, pagination.page * pagination.page_size);
		return `${start}-${end} of ${pagination.total_count}`;
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		const routeKey = `${machineKey}:${page.url.search}`;
		if (routeKey !== loadedRouteKey) {
			loadedMachineKey = machineKey;
			loadedRouteKey = routeKey;
			applyUrlState();
			void loadLibrary();
		}
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<AppHeader />

	<div class="grid gap-6 xl:grid-cols-[18rem_minmax(0,1fr)]">
		<aside class="xl:sticky xl:top-24 xl:self-start">
			<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
				<div class="flex items-center justify-between gap-3">
					<div>
						<div class="dark:text-text-dark text-sm font-semibold text-text">Browse Samples</div>
						<div class="dark:text-text-muted-dark mt-1 text-xs text-text-muted">
							Detection, distillation, and classification evidence in one place.
						</div>
					</div>
					<div class="dark:text-text-muted-dark flex items-center gap-1 text-xs text-text-muted">
						<SlidersHorizontal size={14} />
						{activeFilterCount()}
					</div>
				</div>

				<div class="mt-4 flex flex-col gap-4">
					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Search</div>
						<div class="relative">
							<Search
								size={14}
								class="dark:text-text-muted-dark pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
							/>
							<input
								bind:value={searchDraft}
								onkeydown={(event) => {
									if (event.key === 'Enter') applyFilters();
								}}
								placeholder="sample id, part id, item..."
								class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg py-2 pl-8 pr-2 text-sm text-text"
							/>
						</div>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Session</div>
						<select
							bind:value={selectedSessionId}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All sessions</option>
							{#each facets.sessions as session}
								<option value={session.id}>{session.label} ({session.count})</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Scope</div>
						<select
							bind:value={selectedScope}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All scopes</option>
							{#each facets.detection_scopes as scope}
								<option value={scope}>{humanize(scope)}</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Source Role</div>
						<select
							bind:value={selectedSourceRole}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All roles</option>
							{#each facets.source_roles as role}
								<option value={role}>{humanize(role)}</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Capture Reason</div>
						<select
							bind:value={selectedCaptureReason}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All reasons</option>
							{#each facets.capture_reasons as reason}
								<option value={reason}>{humanize(reason)}</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Detection Algorithm</div>
						<select
							bind:value={selectedDetectionAlgorithm}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All algorithms</option>
							{#each facets.detection_algorithms as algorithm}
								<option value={algorithm}>{humanize(algorithm)}</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Classification Result</div>
						<select
							bind:value={selectedHasClassificationResult}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All samples</option>
							<option value="with">With result</option>
							<option value="without">Without result</option>
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Classification Status</div>
						<select
							bind:value={selectedClassificationStatus}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All statuses</option>
							{#each facets.classification_statuses as status}
								<option value={status}>{humanize(status)}</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Review</div>
						<select
							bind:value={selectedReviewStatus}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All samples</option>
							<option value="unreviewed">Unreviewed</option>
							{#each facets.review_statuses as status}
								<option value={status}>{humanize(status)}</option>
							{/each}
						</select>
					</label>

					<label class="text-xs">
						<div class="dark:text-text-muted-dark mb-1 text-text-muted">Sort By</div>
						<select
							bind:value={sortBy}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							{#each SORT_OPTIONS as option}
								<option value={option.id}>{option.label}</option>
							{/each}
						</select>
					</label>

					<div class="grid grid-cols-2 gap-2">
						<label class="text-xs">
							<div class="dark:text-text-muted-dark mb-1 text-text-muted">Direction</div>
							<select
								bind:value={sortDir}
								class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
							>
								<option value="desc">Newest first</option>
								<option value="asc">Oldest first</option>
							</select>
						</label>
						<label class="text-xs">
							<div class="dark:text-text-muted-dark mb-1 text-text-muted">Page Size</div>
							<select
								bind:value={pageSize}
								class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-2 text-sm text-text"
							>
								{#each PAGE_SIZE_OPTIONS as option}
									<option value={option}>{option}</option>
								{/each}
							</select>
						</label>
					</div>

					<div class="flex gap-2 pt-1">
						<button
							type="button"
							onclick={applyFilters}
							disabled={loading}
							class="border border-sky-500 bg-sky-500/15 px-3 py-2 text-sm text-sky-700 transition-colors hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-sky-300"
						>
							Apply
						</button>
						<button
							type="button"
							onclick={clearFilters}
							disabled={loading || !hasActiveFilters()}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
						>
							<X size={14} class="inline-block" />
							Clear
						</button>
					</div>
					</div>
				</div>

				<div class="dark:border-border-dark dark:bg-surface-dark mt-4 border border-border bg-surface p-4">
					<div class="flex items-center justify-between gap-3">
						<div>
							<div class="dark:text-text-dark text-sm font-semibold text-text">Gemini Queue</div>
							<div class="dark:text-text-muted-dark mt-1 text-xs text-text-muted">
								Background distillation throughput and ETA.
							</div>
						</div>
						<div class="dark:text-text-muted-dark text-[10px] uppercase tracking-[0.16em] text-text-muted">
							{workerStatus?.running ? 'Running' : 'Idle'}
						</div>
					</div>

					<div class="mt-4 grid grid-cols-2 gap-3 text-xs">
						<div class="dark:border-border-dark rounded border border-border p-2">
							<div class="dark:text-text-muted-dark text-text-muted">Pending</div>
							<div class="dark:text-text-dark mt-1 text-lg font-semibold text-text">
								{workerStatus?.pending_count ?? 0}
							</div>
						</div>
						<div class="dark:border-border-dark rounded border border-border p-2">
							<div class="dark:text-text-muted-dark text-text-muted">Queue Depth</div>
							<div class="dark:text-text-dark mt-1 text-lg font-semibold text-text">
								{workerStatus?.queue_depth ?? 0}
							</div>
						</div>
						<div class="dark:border-border-dark rounded border border-border p-2">
							<div class="dark:text-text-muted-dark text-text-muted">Speed</div>
							<div class="dark:text-text-dark mt-1 text-sm font-semibold text-text">
								{formatRate(workerStatus?.items_per_minute)}
							</div>
						</div>
						<div class="dark:border-border-dark rounded border border-border p-2">
							<div class="dark:text-text-muted-dark text-text-muted">ETA</div>
							<div class="dark:text-text-dark mt-1 text-sm font-semibold text-text">
								{formatEta(workerStatus?.eta_seconds)}
							</div>
						</div>
					</div>

					<div class="dark:text-text-muted-dark mt-3 space-y-1 text-[11px] text-text-muted">
						<div>
							Model:
							<span class="dark:text-text-dark text-text">
								{workerStatus?.active_model ? modelShort(workerStatus.active_model) : 'n/a'}
							</span>
						</div>
						<div>
							Scope:
							<span class="dark:text-text-dark text-text">
								{workerStatus?.active_scope ? humanize(workerStatus.active_scope) : 'mixed'}
							</span>
						</div>
						<div>
							Last task:
							<span class="dark:text-text-dark text-text">
								{workerStatus?.last_task_status ? humanize(workerStatus.last_task_status) : 'n/a'}
							</span>
						</div>
					</div>

					<div class="mt-4">
						<div class="dark:text-text-muted-dark mb-2 text-[11px] uppercase tracking-[0.14em] text-text-muted">
							Sample Actions
						</div>
						<div class="grid grid-cols-1 gap-2">
							<button
								type="button"
								onclick={() => retrySamplesByStatus('failed')}
								disabled={loading || bulkActionBusy !== null}
								class="border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-left text-sm text-sky-700 transition-colors hover:bg-sky-500/15 disabled:cursor-not-allowed disabled:opacity-50 dark:text-sky-300"
							>
								{bulkActionBusy === 'retry_failed' ? 'Retrying failed...' : 'Retry Failed'}
							</button>
							<button
								type="button"
								onclick={() => clearSamplesByStatus('failed')}
								disabled={loading || bulkActionBusy !== null}
								class="border border-red-500/40 bg-red-500/10 px-3 py-2 text-left text-sm text-red-700 transition-colors hover:bg-red-500/15 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-300"
							>
								{bulkActionBusy === 'failed' ? 'Clearing failed...' : 'Clear Failed'}
							</button>
							<button
								type="button"
								onclick={() => clearSamplesByStatus('pending')}
								disabled={loading || bulkActionBusy !== null}
								class="border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-left text-sm text-amber-700 transition-colors hover:bg-amber-500/15 disabled:cursor-not-allowed disabled:opacity-50 dark:text-amber-300"
							>
								{bulkActionBusy === 'pending' ? 'Clearing pending...' : 'Clear Pending'}
							</button>
							<button
								type="button"
								onclick={() => clearSamplesByStatus('skipped')}
								disabled={loading || bulkActionBusy !== null}
								class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-2 text-left text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
							>
								{bulkActionBusy === 'skipped' ? 'Clearing skipped...' : 'Clear Skipped'}
							</button>
						</div>
						<div class="dark:text-text-muted-dark mt-2 text-[11px] text-text-muted">
							These actions respect the current sidebar filters.
						</div>
						{#if bulkActionMessage}
							<div
								class={`mt-3 border px-3 py-2 text-xs ${
									bulkActionTone === 'success'
										? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
										: bulkActionTone === 'error'
											? 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
											: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-muted-dark border border-border bg-bg text-text-muted'
								}`}
							>
								{bulkActionMessage}
							</div>
						{/if}
					</div>
				</div>
			</aside>

		<section class="flex min-w-0 flex-col gap-4">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<div>
					<h2 class="dark:text-text-dark text-lg font-semibold text-text">Samples</h2>
					<div class="dark:text-text-muted-dark mt-1 text-sm text-text-muted">
						{pagination.total_count} matching results · {paginationLabel()}
					</div>
				</div>
				<div class="flex items-center gap-2">
					<a
						href="/classification-samples/verify"
						class="border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-600 transition-colors hover:bg-emerald-500/20 dark:text-emerald-400"
					>
						Start Verification
					</a>
					<button
						type="button"
						onclick={loadLibrary}
						disabled={loading}
						class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
					>
						<RefreshCw size={14} class={`mr-1 inline-block ${loading ? 'animate-spin' : ''}`} />
						{loading ? 'Loading...' : 'Reload'}
					</button>
				</div>
			</div>

			{#if errorMsg}
				<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
					{errorMsg}
				</div>
			{/if}

			{#if !loading && samples.length === 0}
				<div class="dark:text-text-muted-dark py-20 text-center text-sm text-text-muted">
					{#if hasActiveFilters()}
						No samples match the current filters.
					{:else}
						No samples yet. Run a detection test or a live classification to start building the library.
					{/if}
				</div>
			{:else}
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
					{#each samples as sample}
						<a
							href={sample.detail_url ?? '#'}
							class="dark:border-border-dark dark:bg-surface-dark group overflow-hidden border border-border bg-surface transition-all hover:border-sky-500/60 hover:shadow-sm"
						>
							<div class="dark:bg-bg-dark relative aspect-square bg-bg">
								{#if assetUrl(sample.overlay_image_url ?? sample.classification_result?.selected_crop_url ?? sample.input_image_url)}
									<img
										src={assetUrl(sample.overlay_image_url ?? sample.classification_result?.selected_crop_url ?? sample.input_image_url) ?? undefined}
										alt=""
										class="h-full w-full object-cover"
									/>
								{:else}
									<div class="dark:text-text-muted-dark flex h-full items-center justify-center text-xs text-text-muted">
										No preview
									</div>
								{/if}

								<div class="absolute left-1 top-1 flex flex-wrap gap-1">
									<span
										class={`inline-block rounded-sm px-1.5 py-0.5 text-[10px] font-medium ${
											sample.distill_status === 'completed'
												? 'bg-emerald-500/90 text-white'
												: sample.distill_status === 'failed'
													? 'bg-red-500/90 text-white'
													: sample.distill_status === 'skipped'
														? 'bg-gray-500/80 text-white'
														: 'bg-amber-500/90 text-white'
										}`}
									>
										{sample.distill_status === 'completed'
											? `${sample.distill_detections ?? sample.detection_bbox_count ?? 0} det`
											: sample.distill_status}
									</span>
									{#if sample.classification_result?.status}
										<span class="inline-block rounded-sm bg-sky-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white">
											{humanize(sample.classification_result.status)}
										</span>
									{/if}
									{#if sample.review_status === 'rejected'}
										<span class="inline-block rounded-sm bg-red-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white">
											Wrong
										</span>
									{:else if sample.review_status === 'accepted'}
										<span class="inline-block rounded-sm bg-emerald-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white">
											Approved
										</span>
									{/if}
								</div>

								{#if sample.retest_count > 0}
									<div class="absolute bottom-1 right-1">
										<span class="inline-block rounded-sm bg-violet-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white">
											{sample.retest_count} retest{sample.retest_count === 1 ? '' : 's'}
										</span>
									</div>
								{/if}
							</div>

							<div class="px-2.5 py-2">
								<div class="flex items-baseline justify-between gap-2">
									<div class="dark:text-text-dark truncate text-xs font-medium text-text">
										{sourceDisplayLabel(sample)}
									</div>
									<div class="dark:text-text-muted-dark shrink-0 text-[10px] text-text-muted">
										{timeAgo(sample.captured_at)}
									</div>
								</div>

								<div class="dark:text-text-muted-dark mt-0.5 truncate text-[10px] text-text-muted">
									{modelShort(sample.detection_openrouter_model) || sample.detection_algorithm || humanize(sample.capture_reason)}
								</div>

								{#if sample.classification_result}
									<div class="dark:text-text-muted-dark mt-0.5 truncate text-[10px] text-text-muted">
										{sample.classification_result.part_id ??
											sample.classification_result.item_name ??
											(sample.classification_result.status
												? `Brickognize ${humanize(sample.classification_result.status).toLowerCase()}`
												: 'Classification result')}
										{#if sample.classification_result.color_name && sample.classification_result.color_name !== 'Any Color'}
											· {sample.classification_result.color_name}
										{/if}
									</div>
								{/if}

								{#if sample.review_status === 'rejected'}
									<div class="mt-1 truncate text-[10px] font-medium text-red-600 dark:text-red-400">
										Marked wrong
									</div>
								{/if}

								<div class="dark:text-text-muted-dark mt-1 flex items-center justify-between gap-2 text-[10px] text-text-muted">
									<span class="truncate">{sample.session_name}</span>
									<span>{formatDate(sample.captured_at).split(',')[0]}</span>
								</div>
							</div>
						</a>
					{/each}
				</div>
			{/if}

			<div class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 dark:border-border-dark">
				<div class="dark:text-text-muted-dark text-sm text-text-muted">
					Page {pagination.page} of {pagination.page_count}
				</div>
				<div class="flex items-center gap-2">
					<button
						type="button"
						onclick={previousPage}
						disabled={loading || pagination.page <= 1}
						class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
					>
						<ChevronLeft size={14} class="mr-1 inline-block" />
						Previous
					</button>
					<button
						type="button"
						onclick={nextPage}
						disabled={loading || pagination.page >= pagination.page_count}
						class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
					>
						Next
						<ChevronRight size={14} class="ml-1 inline-block" />
					</button>
				</div>
			</div>
		</section>
	</div>
</div>
