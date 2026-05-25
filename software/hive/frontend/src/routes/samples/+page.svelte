<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type Machine,
		type PaginatedSamples,
		type SampleFilterOptions,
		type StatsOverview,
		type TeacherJobFilter,
		type TeacherJobSummary
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import { Button } from '$lib/components/primitives';
	import FilterGroup from '$lib/components/sample/FilterGroup.svelte';
	import SampleCard from '$lib/components/SampleCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import {
		readSampleListContext,
		sampleListContextQuery,
		SAMPLE_LIST_DEFAULT_PAGE_SIZE
	} from '$lib/sampleListContext';

	let data = $state<PaginatedSamples | null>(null);
	let machines = $state<Machine[]>([]);
	let filterOptions = $state<SampleFilterOptions>({ source_roles: [], capture_reasons: [] });
	let stats = $state<StatsOverview | null>(null);
	let loading = $state(true);

	// Filters are derived from the URL so reload / share preserves them.
	const listContext = $derived(readSampleListContext(page.url.searchParams));
	// Default scope is "all" — the URL value is only honored when it is the explicit opt-in to
	// "mine". Anything else (missing/empty/other) collapses to all, so a stray query param can't
	// accidentally limit the view.
	const filterScope = $derived(listContext.scope === 'mine' ? 'mine' : 'all');
	const filterMachine = $derived(listContext.machine_id ?? '');
	const filterStatus = $derived(listContext.review_status ?? '');
	const filterSourceRole = $derived(listContext.source_role ?? '');
	const filterCaptureReason = $derived(listContext.capture_reason ?? '');
	// 'regular' (default once a filter is picked, also means: no condition crops)
	// or 'condition'. Empty string = all = both kinds mixed.
	const filterKind = $derived(listContext.kind ?? '');
	// Per-user review filter — independent of the global review_status pill.
	// 'unreviewed' = I haven't reviewed; 'accepted' / 'rejected' = my own
	// past decision; 'reviewed' = I reviewed either way.
	const filterMyReview = $derived(listContext.my_review ?? '');
	// 'teacher' = already validated by a Hive teacher pass;
	// 'raw' = still raw sorter detections, often incomplete (Dave's freshly
	// uploaded samples typically fall here until the teacher worker has
	// caught up). Default '' shows both.
	const filterAnnotated = $derived(listContext.annotated ?? '');

	// Lookup tables for collapsed-filter chip labels. Defined once at the
	// script top so the markup can reference them without {@const} hoisting.
	const MY_REVIEW_LABELS: Record<string, string> = {
		unreviewed: 'Not by me yet',
		reviewed: 'By me',
		accepted: 'I accepted',
		rejected: 'I rejected'
	};
	const STATUS_LABELS: Record<string, string> = {
		unreviewed: 'Unreviewed',
		in_review: 'In Review',
		accepted: 'Accepted',
		rejected: 'Rejected',
		conflict: 'Conflict'
	};
	// Histogram bucket — 'under' / 'normal' / 'over' / 'all'. Empty = no filter.
	const filterExposure = $derived(listContext.exposure ?? '');
	// Admin-only: 'active' (default), 'archived', 'all'. Server enforces:
	// non-admins always see active regardless of what they send.
	const filterArchived = $derived(listContext.archived ?? '');
	const filterMaxAgeHours = $derived(listContext.max_age_hours ?? '');
	const currentPage = $derived(listContext.page);
	const pageSize = $derived(listContext.page_size);

	const AGE_OPTIONS: { value: string; label: string }[] = [
		{ value: '', label: 'All' },
		{ value: '24', label: 'Last 24h' },
		{ value: '168', label: 'Last 7 days' },
		{ value: '720', label: 'Last 30 days' }
	];

	const filterContextQuery = $derived(sampleListContextQuery(page.url.searchParams));

	const sourceRoleLabels: Record<string, string> = {
		c_channel_1: 'C1',
		c_channel_2: 'C2',
		c_channel_3: 'C3',
		classification_channel: 'C-Channel 4 (Classification)',
		classification_chamber: 'Classification Chamber',
		carousel: 'Carousel',
		piece_crop: 'Piece Crop',
		top: 'Top Camera',
		bottom: 'Bottom Camera'
	};

	const statusColors: Record<string, string> = {
		accepted: 'bg-success',
		rejected: 'bg-primary',
		in_review: 'bg-info',
		conflict: 'bg-warning',
		unreviewed: 'bg-border'
	};

	const hasActiveFilters = $derived(
		filterMachine || filterStatus || filterSourceRole || filterCaptureReason || filterKind || filterMyReview || filterAnnotated || filterExposure || filterArchived || filterMaxAgeHours
	);

	$effect(() => {
		void filterScope;
		void loadFilters();
	});

	$effect(() => {
		void filterScope;
		void filterMachine;
		void filterStatus;
		void filterSourceRole;
		void filterCaptureReason;
		void filterKind;
		void filterMyReview;
		void filterAnnotated;
		void filterExposure;
		void filterArchived;
		void filterMaxAgeHours;
		void currentPage;
		void pageSize;
		loadSamples();
	});

	function pushFilterUrl(mutate: (sp: URLSearchParams) => void) {
		const url = new URL(page.url);
		mutate(url.searchParams);
		const search = url.searchParams.toString();
		void goto(`${url.pathname}${search ? `?${search}` : ''}`, {
			replaceState: false,
			noScroll: true,
			keepFocus: true
		});
	}

	function setFilterValue(key: string, value: string, resetPage = true) {
		pushFilterUrl((sp) => {
			if (value) sp.set(key, value);
			else sp.delete(key);
			if (resetPage) sp.delete('page');
		});
	}

	async function loadFilters() {
		try {
			const scope = filterScope;
			const [nextMachines, nextOptions, nextStats] = await Promise.all([
				api.getMachines({ scope }),
				api.getSampleFilterOptions({ scope }),
				api.getOverview({ scope })
			]);
			machines = nextMachines;
			filterOptions = nextOptions;
			stats = nextStats;
		} catch {
			// ignore
		}
	}

	async function restoreActiveTeacherJob() {
		if (auth.user?.role !== 'admin') return;
		try {
			const jobs = await api.listTeacherJobs();
			const active = jobs.find((j) => j.status === 'pending' || j.status === 'running');
			if (active) {
				teacherJob = active;
				startTeacherPolling();
			}
		} catch {
			// ignore — restoring the banner is best-effort
		}
	}

	$effect(() => {
		// Reattach the banner on mount so reloading the page doesn't make a running job
		// invisible. Polling kicks back in once we find one.
		void restoreActiveTeacherJob();
	});

	async function loadSamples() {
		loading = true;
		try {
			data = await api.getSamples({
				page: currentPage,
				page_size: pageSize,
				scope: filterScope,
				machine_id: filterMachine || undefined,
				review_status: filterStatus || undefined,
				source_role: filterSourceRole || undefined,
				capture_reason: filterCaptureReason || undefined,
				kind: filterKind || undefined,
				my_review: filterMyReview || undefined,
				annotated: filterAnnotated || undefined,
				exposure: filterExposure || undefined,
				archived: filterArchived || undefined,
				max_age_hours: filterMaxAgeHours || undefined
			});
		} catch {
			data = null;
		} finally {
			loading = false;
		}
	}

	// Group machines under their owner when looking at all samples so the sidebar reads as a
	// roster of contributors instead of an undifferentiated machine list.
	type MachineGroup = { ownerKey: string; ownerLabel: string; machines: Machine[] };
	const machineGroups = $derived.by<MachineGroup[]>(() => {
		if (filterScope === 'mine') {
			return [{ ownerKey: '__self', ownerLabel: 'My machines', machines }];
		}
		const buckets = new Map<string, MachineGroup>();
		const myId = auth.user?.id ?? null;
		for (const machine of machines) {
			const ownerId = machine.owner?.id ?? machine.owner_id ?? 'unknown';
			const isSelf = myId !== null && ownerId === myId;
			const label = isSelf
				? 'Me'
				: machine.owner?.display_name?.trim() || 'Unknown user';
			const key = isSelf ? '__self' : ownerId;
			let bucket = buckets.get(key);
			if (!bucket) {
				bucket = { ownerKey: key, ownerLabel: label, machines: [] };
				buckets.set(key, bucket);
			}
			bucket.machines.push(machine);
		}
		return Array.from(buckets.values()).sort((a, b) => {
			if (a.ownerKey === '__self') return -1;
			if (b.ownerKey === '__self') return 1;
			return a.ownerLabel.localeCompare(b.ownerLabel);
		});
	});

	function prettifyToken(value: string): string {
		return value
			.split('_')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
	}

	function sourceRoleLabel(value: string): string {
		return sourceRoleLabels[value] ?? prettifyToken(value);
	}

	function sourceRoleCount(value: string): number {
		return filterOptions.source_role_counts?.[value] ?? 0;
	}

	function totalSourceRoleCount(): number {
		return Object.values(filterOptions.source_role_counts ?? {}).reduce((sum, count) => {
			return sum + (Number.isFinite(count) ? count : 0);
		}, 0);
	}

	function goToPage(target: number) {
		pushFilterUrl((sp) => {
			if (target <= 1) sp.delete('page');
			else sp.set('page', String(target));
		});
	}

	function changePageSize(size: number) {
		pushFilterUrl((sp) => {
			if (size === SAMPLE_LIST_DEFAULT_PAGE_SIZE) sp.delete('page_size');
			else sp.set('page_size', String(size));
			sp.delete('page');
		});
	}

	function setStatusFilter(status: string) {
		const next = filterStatus === status ? '' : status;
		setFilterValue('review_status', next);
	}

	function setScope(next: 'mine' | 'all') {
		if (next === filterScope) return;
		// Switching scope changes the visible machine pool — drop the machine filter so we
		// don't end up showing zero results because the previously selected machine isn't in
		// the new scope.
		pushFilterUrl((sp) => {
			if (next === 'mine') sp.set('scope', 'mine');
			else sp.delete('scope');
			sp.delete('machine_id');
			sp.delete('page');
		});
	}

	function updateMachineFilter(value: string) {
		setFilterValue('machine_id', value);
	}

	function updateSourceRoleFilter(value: string) {
		setFilterValue('source_role', value);
	}

	function updateAgeFilter(value: string) {
		setFilterValue('max_age_hours', value);
	}

	function clearFilters() {
		// 'scope' is a viewing context, not a per-search filter — keep it across "Clear all".
		pushFilterUrl((sp) => {
			sp.delete('machine_id');
			sp.delete('review_status');
			sp.delete('source_role');
			sp.delete('capture_reason');
			sp.delete('kind');
			sp.delete('my_review');
			sp.delete('annotated');
			sp.delete('exposure');
			sp.delete('archived');
			sp.delete('max_age_hours');
			sp.delete('page');
		});
	}

	// --- Teacher rerun (admin only) ------------------------------------------------
	// Source roles the Hive teacher has prompt zones for. Must mirror SOURCE_ROLE_TO_ZONE
	// in app/services/teacher_detector.py — anything else is filtered out server-side.
	const TEACHER_SUPPORTED_ROLES = new Set([
		'classification_chamber',
		'carousel',
		'classification_channel',
		'c_channel',
		'c_channel_1',
		'c_channel_2',
		'c_channel_3',
		'c_channel_full'
	]);

	let teacherModalOpen = $state(false);
	let teacherSubmitting = $state(false);
	let teacherJob = $state<TeacherJobSummary | null>(null);
	let teacherError = $state<string | null>(null);
	let teacherPollTimer: ReturnType<typeof setInterval> | null = null;

	// Batch-delete UI state. Two-step: open the modal, hit dry-run for the
	// count, then a separate Confirm click runs the destructive POST. The
	// button is hidden unless scope=mine so a misclick can't even start the
	// flow when looking at the global library.
	let deleteModalOpen = $state(false);
	let deleteCount = $state<number | null>(null);
	let deleteCapped = $state(false);
	let deleteRunning = $state(false);
	let deleteError = $state<string | null>(null);
	let deleteResult = $state<{ deleted: number; matched: number } | null>(null);

	const currentBatchDeletePayload = $derived(() => ({
		machine_id: filterMachine || undefined,
		source_role: filterSourceRole || undefined,
		capture_reason: filterCaptureReason || undefined,
		review_status: filterStatus || undefined,
		kind: filterKind || undefined,
		my_review: filterMyReview || undefined,
		annotated: filterAnnotated || undefined,
		// Mirror the server-side default ('not_under') so a "Delete /
		// Archive filtered" from the default view operates on exactly the
		// samples the operator can see — not on the underexposed batch
		// that's hidden by default.
		exposure: filterExposure || 'not_under',
		max_age_hours: filterMaxAgeHours ? Number(filterMaxAgeHours) : undefined
	}));

	async function openDeleteModal() {
		deleteModalOpen = true;
		deleteCount = null;
		deleteCapped = false;
		deleteError = null;
		deleteResult = null;
		try {
			const res = await api.batchDeleteSamples({
				...currentBatchDeletePayload(),
				dry_run: true
			});
			deleteCount = res.matched;
			deleteCapped = res.capped;
		} catch (e) {
			deleteError = e instanceof Error ? e.message : 'Count probe failed.';
		}
	}

	function closeDeleteModal() {
		if (deleteRunning) return;
		deleteModalOpen = false;
		deleteCount = null;
		deleteCapped = false;
		deleteError = null;
		deleteResult = null;
	}

	async function runBatchDelete() {
		if (deleteRunning || deleteCount === null || deleteCount === 0 || deleteCapped) return;
		deleteRunning = true;
		deleteError = null;
		try {
			const res = await api.batchDeleteSamples(currentBatchDeletePayload());
			deleteResult = { deleted: res.deleted, matched: res.matched };
			// Refresh the visible page + filter facets.
			await loadSamples();
			await loadFilters();
		} catch (e) {
			deleteError = e instanceof Error ? e.message : 'Delete failed.';
		} finally {
			deleteRunning = false;
		}
	}

	// Admin-only batch archive. Reversible (no file deletion); operates on
	// the full library (no ownership constraint, server enforces admin role).
	let archiveMode = $state<'archive' | 'unarchive'>('archive');
	let archiveModalOpen = $state(false);
	let archiveCount = $state<number | null>(null);
	let archiveCapped = $state(false);
	let archiveRunning = $state(false);
	let archiveError = $state<string | null>(null);
	let archiveResult = $state<{ archived: number; matched: number; mode: 'archive' | 'unarchive' } | null>(null);

	const currentBatchArchivePayload = $derived(() => ({
		machine_id: filterMachine || undefined,
		source_role: filterSourceRole || undefined,
		capture_reason: filterCaptureReason || undefined,
		review_status: filterStatus || undefined,
		kind: filterKind || undefined,
		my_review: filterMyReview || undefined,
		annotated: filterAnnotated || undefined,
		// Mirror the server-side default ('not_under') so a "Delete /
		// Archive filtered" from the default view operates on exactly the
		// samples the operator can see — not on the underexposed batch
		// that's hidden by default.
		exposure: filterExposure || 'not_under',
		max_age_hours: filterMaxAgeHours ? Number(filterMaxAgeHours) : undefined
	}));

	async function openArchiveModal(mode: 'archive' | 'unarchive') {
		archiveMode = mode;
		archiveModalOpen = true;
		archiveCount = null;
		archiveCapped = false;
		archiveError = null;
		archiveResult = null;
		try {
			const res = await api.batchArchiveSamples(
				{ ...currentBatchArchivePayload(), dry_run: true },
				mode
			);
			archiveCount = res.matched;
			archiveCapped = res.capped;
		} catch (e) {
			archiveError = e instanceof Error ? e.message : 'Count probe failed.';
		}
	}

	function closeArchiveModal() {
		if (archiveRunning) return;
		archiveModalOpen = false;
		archiveCount = null;
		archiveCapped = false;
		archiveError = null;
		archiveResult = null;
	}

	async function runBatchArchive() {
		if (archiveRunning || archiveCount === null || archiveCount === 0 || archiveCapped) return;
		archiveRunning = true;
		archiveError = null;
		try {
			const res = await api.batchArchiveSamples(currentBatchArchivePayload(), archiveMode);
			archiveResult = { archived: res.archived, matched: res.matched, mode: archiveMode };
			await loadSamples();
			await loadFilters();
		} catch (e) {
			archiveError = e instanceof Error ? e.message : 'Archive failed.';
		} finally {
			archiveRunning = false;
		}
	}

	const currentTeacherFilter = $derived<TeacherJobFilter>({
		scope: filterScope,
		machine_id: filterMachine || undefined,
		review_status: filterStatus || undefined,
		source_role: filterSourceRole || undefined,
		capture_reason: filterCaptureReason || undefined,
		kind: filterKind || undefined,
		my_review: filterMyReview || undefined,
		// Only forward an explicit annotated filter ('teacher' / 'raw' /
		// 'all'). Empty stays undefined so a default-view re-run sweeps
		// everything matching the other filters — re-running teacher is
		// usually meant as a broad re-pass, not "only what's already been
		// teacher'd" which is what mirroring the server default would imply.
		annotated: filterAnnotated || undefined,
		exposure: filterExposure || undefined,
		// Age filter must travel with the job filter — otherwise the modal counts a 24h
		// slice but the job picks up the full table.
		max_age_hours: filterMaxAgeHours ? Number(filterMaxAgeHours) : undefined
	});

	const teacherEligibleCount = $derived.by(() => {
		if (!data) return null;
		// Approximate using what we have in the current page when no source_role filter is
		// applied; if a source_role filter narrows the set, the server count == the visible
		// total so we just return stats.total_samples shaped accordingly.
		if (filterSourceRole) {
			return TEACHER_SUPPORTED_ROLES.has(filterSourceRole) ? data.total : 0;
		}
		// Otherwise we don't know without a roundtrip — present the page-wide total and let
		// the server reject unsupported roles silently.
		return data.total;
	});

	async function openTeacherModal() {
		teacherError = null;
		teacherModalOpen = true;
	}

	async function submitTeacherJob() {
		teacherSubmitting = true;
		teacherError = null;
		try {
			const job = await api.createTeacherJob(currentTeacherFilter);
			teacherJob = job;
			teacherModalOpen = false;
			startTeacherPolling();
		} catch (err) {
			const message =
				err && typeof err === 'object' && 'error' in err
					? String((err as { error: unknown }).error)
					: 'Failed to start teacher job';
			teacherError = message;
		} finally {
			teacherSubmitting = false;
		}
	}

	function startTeacherPolling() {
		stopTeacherPolling();
		teacherPollTimer = setInterval(async () => {
			if (!teacherJob) return;
			try {
				teacherJob = await api.getTeacherJob(teacherJob.id);
				if (teacherJob.status === 'done' || teacherJob.status === 'cancelled') {
					stopTeacherPolling();
					// Refresh the samples list now that detections may have been overwritten.
					await loadSamples();
				}
			} catch {
				// transient errors are fine — keep polling
			}
		}, 3000);
	}

	function stopTeacherPolling() {
		if (teacherPollTimer !== null) {
			clearInterval(teacherPollTimer);
			teacherPollTimer = null;
		}
	}

	async function cancelTeacherJob() {
		if (!teacherJob) return;
		try {
			teacherJob = await api.cancelTeacherJob(teacherJob.id);
		} catch {
			// ignore — UI keeps showing latest known state
		}
	}

	function dismissTeacherJob() {
		stopTeacherPolling();
		teacherJob = null;
	}

	// Live wall-clock that ticks once a second so the ETA chip recomputes between
	// the slower 3s job-poll cycles — otherwise the time-remaining label would
	// only refresh on each polled state change.
	let nowMs = $state(Date.now());
	let nowTicker: ReturnType<typeof setInterval> | null = null;
	$effect(() => {
		nowTicker = setInterval(() => { nowMs = Date.now(); }, 1000);
		return () => {
			if (nowTicker) clearInterval(nowTicker);
		};
	});

	function formatRemaining(seconds: number): string {
		if (!Number.isFinite(seconds) || seconds < 0) return '—';
		if (seconds < 60) return `${Math.round(seconds)}s`;
		const totalMins = Math.round(seconds / 60);
		if (totalMins < 60) return `${totalMins}m`;
		const hours = Math.floor(totalMins / 60);
		const mins = totalMins % 60;
		return mins === 0 ? `${hours}h` : `${hours}h ${mins}m`;
	}

	function computeEta(job: TeacherJobSummary): {
		remainingLabel: string;
		rate: number;
		startedAtLabel: string;
	} | null {
		// Only meaningful while the job is in-flight with measurable progress.
		if (job.status !== 'running' && job.status !== 'pending') return null;
		if (!job.started_at || job.processed <= 0 || job.processed >= job.total) return null;
		const startMs = new Date(job.started_at).getTime();
		if (!Number.isFinite(startMs)) return null;
		const elapsedSec = Math.max(1, (nowMs - startMs) / 1000);
		const rate = job.processed / elapsedSec;
		if (rate <= 0) return null;
		const remaining = (job.total - job.processed) / rate;
		return {
			remainingLabel: formatRemaining(remaining),
			rate,
			startedAtLabel: new Date(job.started_at).toLocaleTimeString('de-DE', {
				hour: '2-digit', minute: '2-digit'
			})
		};
	}

	$effect(() => {
		return () => stopTeacherPolling();
	});
</script>

<svelte:head>
	<title>Samples - Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<div>
		<h1 class="text-2xl font-bold text-text">Samples</h1>
		<p class="mt-1 text-sm text-text-muted">
			Browse and review training samples captured by your machines.
		</p>
	</div>
	<div class="flex items-center gap-2">
		<a
			href="/samples/diversity"
			class="inline-flex items-center gap-2 border border-border bg-white px-4 py-2 text-sm font-medium text-text hover:bg-bg"
		>
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
			</svg>
			Diversity
		</a>
		{#if auth.user?.role === 'admin'}
			<a
				href="/admin/teacher-jobs"
				class="inline-flex items-center gap-2 border border-border bg-white px-4 py-2 text-sm font-medium text-text hover:bg-bg"
				title="See all running and past Gemini teacher jobs."
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z" />
				</svg>
				Jobs
			</a>
			<button
				type="button"
				onclick={openTeacherModal}
				class="inline-flex items-center gap-2 border border-border bg-white px-4 py-2 text-sm font-medium text-text hover:bg-bg"
				title="Re-run the Gemini teacher across samples matching the current filter. Overwrites detection_bboxes and resets review status."
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
				</svg>
				Re-run teacher
			</button>
		{/if}
		{#if auth.user?.role === 'admin'}
			<!-- Admin-only soft-delete. Shows Unarchive when looking at the
			     archived-only view; Archive otherwise. -->
			<button
				type="button"
				onclick={() => openArchiveModal(filterArchived === 'archived' ? 'unarchive' : 'archive')}
				class="inline-flex items-center gap-2 border border-border px-4 py-2 text-sm font-medium text-text hover:border-text hover:bg-text hover:text-white"
				title={hasActiveFilters
					? (filterArchived === 'archived'
						? 'Unarchive every sample matching the current filter'
						: 'Archive every sample matching the current filter')
					: (filterArchived === 'archived'
						? 'Unarchive every currently-archived sample (no filter active)'
						: 'Archive every sample in the library (no filter active)')}
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
				</svg>
				{filterArchived === 'archived' ? 'Unarchive filtered' : 'Archive filtered'}
			</button>
		{/if}
		{#if filterScope === 'mine'}
			<!-- Destructive: only shown when looking at "My samples" so an
			     admin browsing the global library can't even start the flow. -->
			<button
				type="button"
				onclick={openDeleteModal}
				class="inline-flex items-center gap-2 border border-danger px-4 py-2 text-sm font-medium text-danger hover:bg-danger hover:text-white"
				title={hasActiveFilters
					? 'Delete every sample that matches the current sidebar filter'
					: 'Delete every one of your samples (no filter active)'}
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
				</svg>
				Delete {hasActiveFilters ? 'filtered' : 'all mine'}
			</button>
		{/if}
		{#if auth.isReviewer}
			{@const reviewHref = (() => {
				// Forward the same sidebar filters to the review queue so the reviewer drains
				// only the slice they have selected (e.g. "C-Channel 4, last 24h"). Empty
				// values are omitted so a plain click with no filter behaves as before.
				const sp = new URLSearchParams();
				if (filterScope === 'mine') sp.set('scope', 'mine');
				if (filterMachine) sp.set('machine_id', filterMachine);
				if (filterSourceRole) sp.set('source_role', filterSourceRole);
				if (filterCaptureReason) sp.set('capture_reason', filterCaptureReason);
				if (filterKind) sp.set('kind', filterKind);
				if (filterAnnotated) sp.set('annotated', filterAnnotated);
				if (filterExposure) sp.set('exposure', filterExposure);
				if (filterMaxAgeHours) sp.set('max_age_hours', filterMaxAgeHours);
				// Forward review_status + my_review so e.g. "show me conflict
				// samples" or "show me what I already accepted" carries into
				// the queue. The queue treats either as 'revisit mode' and
				// drops its default "fresh work" gates.
				if (filterStatus) sp.set('review_status', filterStatus);
				if (filterMyReview) sp.set('my_review', filterMyReview);
				const qs = sp.toString();
				return qs ? `/review?${qs}` : '/review';
			})()}
			<a
				href={reviewHref}
				class="inline-flex items-center gap-2 bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
				title={hasActiveFilters ? 'Review only the samples matching the current filter' : 'Open the full review queue'}
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
				</svg>
				Review {hasActiveFilters ? 'filtered' : 'Samples'}
			</a>
		{/if}
	</div>
</div>

{#if teacherJob}
	{@const job = teacherJob}
	{@const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0}
	{@const eta = computeEta(job)}
	<div class="mb-4 border border-border bg-white">
		<div class="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
			<div class="flex items-center gap-2 text-xs">
				<span class="font-semibold text-text">Teacher job</span>
				<span class="text-text-muted">{job.openrouter_model}</span>
				<span class="tabular-nums text-text">{job.processed}/{job.total}</span>
				<span class="text-text-muted">
					({job.succeeded} ok{job.failed > 0 ? ` · ${job.failed} failed` : ''})
				</span>
				<span
					class="tabular-nums text-text-muted"
					title="Real billed cost so far / projected total based on running average."
				>
					· {job.cost_usd === 0 ? '$0.00' : (Math.abs(job.cost_usd) < 0.01 ? `$${job.cost_usd.toFixed(4)}` : `$${job.cost_usd.toFixed(2)}`)}
					{#if job.cost_usd_estimated_total != null && (job.status === 'pending' || job.status === 'running')}
						{@const est = job.cost_usd_estimated_total}
						/ est. {est === 0 ? '$0.00' : (Math.abs(est) < 0.01 ? `$${est.toFixed(4)}` : `$${est.toFixed(2)}`)}
					{/if}
				</span>
				<span class="text-text-muted">· {job.status}</span>
				{#if eta}
					<span
						class="tabular-nums text-text-muted"
						title={`Based on ${eta.rate.toFixed(2)} items/sec since ${eta.startedAtLabel}. Updates every refresh.`}
					>
						· ETA {eta.remainingLabel}
					</span>
				{/if}
			</div>
			<div class="flex items-center gap-3">
				<a href={`/admin/teacher-jobs/${job.id}`} class="text-xs text-primary hover:underline">
					Open details →
				</a>
				<a href="/admin/teacher-jobs" class="text-xs text-text-muted hover:text-primary">
					All jobs
				</a>
				{#if job.status === 'pending' || job.status === 'running'}
					<button type="button" onclick={cancelTeacherJob} class="text-xs text-text-muted hover:text-primary">
						Cancel
					</button>
				{:else}
					<button type="button" onclick={dismissTeacherJob} class="text-xs text-text-muted hover:text-text">
						Dismiss
					</button>
				{/if}
			</div>
		</div>
		<div class="h-1.5 bg-bg">
			<div
				class="h-full transition-[width] duration-300 {job.status === 'cancelled' ? 'bg-border' : 'bg-primary'}"
				style="width: {pct}%"
			></div>
		</div>
		{#if job.last_error}
			<div class="px-4 py-2 text-[11px] text-warning">Last error: {job.last_error}</div>
		{/if}
	</div>
{/if}

<Modal
	open={archiveModalOpen}
	title={archiveMode === 'archive' ? 'Archive filtered samples' : 'Unarchive filtered samples'}
	onclose={closeArchiveModal}
>
	<div class="space-y-4 text-sm">
		{#if archiveError}
			<div class="border border-danger bg-danger/10 px-3 py-2 text-xs text-danger">
				{archiveError}
			</div>
		{/if}

		{#if archiveResult}
			<p class="text-text">
				{archiveResult.mode === 'archive' ? 'Archived' : 'Unarchived'}
				<span class="font-semibold">{archiveResult.archived}</span>
				sample{archiveResult.archived === 1 ? '' : 's'}.
			</p>
		{:else if archiveCount === null}
			<p class="text-text-muted">Counting…</p>
		{:else if archiveCount === 0}
			<p class="text-text">
				No {archiveMode === 'archive' ? 'active' : 'archived'} samples match the current filter.
			</p>
		{:else}
			<p class="text-text">
				{#if archiveMode === 'archive'}
					Archive <span class="font-semibold">{archiveCount.toLocaleString()}</span>
					sample{archiveCount === 1 ? '' : 's'} matching the current filter?
				{:else}
					Restore <span class="font-semibold">{archiveCount.toLocaleString()}</span>
					archived sample{archiveCount === 1 ? '' : 's'} back into circulation?
				{/if}
			</p>
			<ul class="space-y-1 text-xs text-text-muted">
				{#if archiveMode === 'archive'}
					<li>• Hidden from the sample list, review queue and training pulls.</li>
					<li>• Files + sample_payload stay intact — reversible via Unarchive.</li>
					<li>• Admin-only action, applied across the global library.</li>
				{:else}
					<li>• Samples reappear in listings, review queue and training pulls.</li>
					<li>• No data changes besides clearing the archived_at flag.</li>
				{/if}
			</ul>
			{#if hasActiveFilters}
				<div class="border border-border bg-bg px-3 py-2 text-xs">
					<div class="mb-1 font-semibold text-text-muted">Active filter</div>
					<div class="flex flex-wrap gap-1.5">
						{#if filterScope === 'mine'}<span class="border border-border px-1.5 py-0.5 text-text">scope=mine</span>{/if}
						{#if filterMachine}<span class="border border-border px-1.5 py-0.5 text-text">machine={filterMachine}</span>{/if}
						{#if filterSourceRole}<span class="border border-border px-1.5 py-0.5 text-text">source_role={filterSourceRole}</span>{/if}
						{#if filterCaptureReason}<span class="border border-border px-1.5 py-0.5 text-text">capture_reason={filterCaptureReason}</span>{/if}
						{#if filterStatus}<span class="border border-border px-1.5 py-0.5 text-text">status={filterStatus}</span>{/if}
						{#if filterKind}<span class="border border-border px-1.5 py-0.5 text-text">kind={filterKind}</span>{/if}
						{#if filterMyReview}<span class="border border-border px-1.5 py-0.5 text-text">my_review={filterMyReview}</span>{/if}
						{#if filterAnnotated}<span class="border border-border px-1.5 py-0.5 text-text">annotated={filterAnnotated}</span>{/if}
						{#if filterExposure}<span class="border border-border px-1.5 py-0.5 text-text">exposure={filterExposure}</span>{/if}
						{#if filterMaxAgeHours}<span class="border border-border px-1.5 py-0.5 text-text">max_age_hours={filterMaxAgeHours}</span>{/if}
					</div>
				</div>
			{:else}
				<div class="border border-warning bg-warning/10 px-3 py-2 text-xs text-text">
					No filter active — this will {archiveMode === 'archive' ? 'archive every active sample in the library' : 'unarchive every currently-archived sample'}. Narrow with the sidebar first if you only want a slice.
				</div>
			{/if}
			{#if archiveCapped}
				<div class="border border-warning bg-warning/10 px-3 py-2 text-xs text-text">
					Match count exceeds the 20,000-per-call cap. Narrow the filter and try again.
				</div>
			{/if}
		{/if}

		<div class="flex justify-end gap-2 border-t border-border pt-3">
			<Button variant="secondary" onclick={closeArchiveModal} disabled={archiveRunning}>
				{archiveResult ? 'Close' : 'Cancel'}
			</Button>
			{#if !archiveResult}
				<Button
					variant="primary"
					onclick={runBatchArchive}
					disabled={archiveRunning || archiveCount === null || archiveCount === 0 || archiveCapped}
					loading={archiveRunning}
				>
					{#if archiveCount && archiveCount > 0}
						{archiveMode === 'archive' ? `Archive ${archiveCount.toLocaleString()}` : `Unarchive ${archiveCount.toLocaleString()}`}
					{:else}
						{archiveMode === 'archive' ? 'Archive' : 'Unarchive'}
					{/if}
				</Button>
			{/if}
		</div>
	</div>
</Modal>

<Modal open={deleteModalOpen} title="Delete filtered samples" onclose={closeDeleteModal}>
	<div class="space-y-4 text-sm">
		{#if deleteError}
			<div class="border border-danger bg-danger/10 px-3 py-2 text-xs text-danger">
				{deleteError}
			</div>
		{/if}

		{#if deleteResult}
			<p class="text-text">
				Deleted <span class="font-semibold">{deleteResult.deleted}</span>
				sample{deleteResult.deleted === 1 ? '' : 's'}.
			</p>
		{:else if deleteCount === null}
			<p class="text-text-muted">Counting…</p>
		{:else if deleteCount === 0}
			<p class="text-text">No samples match the current filter.</p>
		{:else}
			<p class="text-text">
				Permanently delete <span class="font-semibold">{deleteCount.toLocaleString()}</span>
				sample{deleteCount === 1 ? '' : 's'} that you own and match the current filter?
			</p>
			<ul class="space-y-1 text-xs text-text-muted">
				<li>• Images, full frames, overlays and annotations are dropped from storage.</li>
				<li>• Cannot be undone.</li>
				<li>• Only your own samples are touched — others' rigs are unaffected even if the filter would match them.</li>
			</ul>
			{#if hasActiveFilters}
				<div class="border border-border bg-bg px-3 py-2 text-xs">
					<div class="mb-1 font-semibold text-text-muted">Active filter</div>
					<div class="flex flex-wrap gap-1.5">
						{#if filterMachine}<span class="border border-border px-1.5 py-0.5 text-text">machine={filterMachine}</span>{/if}
						{#if filterSourceRole}<span class="border border-border px-1.5 py-0.5 text-text">source_role={filterSourceRole}</span>{/if}
						{#if filterCaptureReason}<span class="border border-border px-1.5 py-0.5 text-text">capture_reason={filterCaptureReason}</span>{/if}
						{#if filterStatus}<span class="border border-border px-1.5 py-0.5 text-text">status={filterStatus}</span>{/if}
						{#if filterKind}<span class="border border-border px-1.5 py-0.5 text-text">kind={filterKind}</span>{/if}
						{#if filterMyReview}<span class="border border-border px-1.5 py-0.5 text-text">my_review={filterMyReview}</span>{/if}
						{#if filterAnnotated}<span class="border border-border px-1.5 py-0.5 text-text">annotated={filterAnnotated}</span>{/if}
						{#if filterExposure}<span class="border border-border px-1.5 py-0.5 text-text">exposure={filterExposure}</span>{/if}
						{#if filterMaxAgeHours}<span class="border border-border px-1.5 py-0.5 text-text">max_age_hours={filterMaxAgeHours}</span>{/if}
					</div>
				</div>
			{:else}
				<div class="border border-warning bg-warning/10 px-3 py-2 text-xs text-text">
					No filter active — this will delete <em>every</em> sample you own. Narrow with the sidebar first if you only want a slice.
				</div>
			{/if}
			{#if deleteCapped}
				<div class="border border-warning bg-warning/10 px-3 py-2 text-xs text-text">
					Match count exceeds the 5,000-per-call cap. Narrow the filter before pressing Delete.
				</div>
			{/if}
		{/if}

		<div class="flex justify-end gap-2 border-t border-border pt-3">
			<Button variant="secondary" onclick={closeDeleteModal} disabled={deleteRunning}>
				{deleteResult ? 'Close' : 'Cancel'}
			</Button>
			{#if !deleteResult}
				<Button
					variant="danger"
					onclick={runBatchDelete}
					disabled={deleteRunning || deleteCount === null || deleteCount === 0 || deleteCapped}
					loading={deleteRunning}
				>
					{deleteCount && deleteCount > 0
						? `Delete ${deleteCount.toLocaleString()}`
						: 'Delete'}
				</Button>
			{/if}
		</div>
	</div>
</Modal>

<Modal open={teacherModalOpen} title="Re-run Gemini teacher" onclose={() => { teacherModalOpen = false; }}>
	<div class="space-y-4 text-sm">
		<p class="text-text">
			Run the Gemini detector across <span class="font-semibold">{teacherEligibleCount ?? '…'}</span>
			sample{teacherEligibleCount === 1 ? '' : 's'} matching the current filter.
			Unsupported source roles (no prompt zone) are skipped.
		</p>
		<ul class="space-y-1 text-xs text-text-muted">
			<li>• Overwrites <code>detection_bboxes</code>, <code>detection_count</code> and <code>detection_score</code>.</li>
			<li>• Resets <code>review_status</code> to <em>unreviewed</em> so the new boxes go through review again.</li>
			<li>• Uses the OpenRouter API key from your profile.</li>
			<li>• Rate-limited to ~1 sample / second to respect Gemini's per-key quota.</li>
		</ul>
		{#if teacherError}
			<div class="border border-warning-strong bg-warning-bg px-3 py-2 text-xs text-warning-strong">{teacherError}</div>
		{/if}
		<div class="flex justify-end gap-2">
			<Button variant="secondary" onclick={() => { teacherModalOpen = false; }}>Cancel</Button>
			<Button variant="primary" loading={teacherSubmitting} onclick={submitTeacherJob}>
				Start job
			</Button>
		</div>
	</div>
</Modal>

<!-- Stats bar -->
{#if stats && stats.total_samples > 0}
	{@const segments = [
		{ key: 'accepted', label: 'Accepted', count: stats.accepted_samples, color: '#00852B' },
		{ key: 'rejected', label: 'Rejected', count: stats.rejected_samples, color: '#D01012' },
		{ key: 'in_review', label: 'In Review', count: stats.in_review_samples, color: '#0055BF' },
		{ key: 'conflict', label: 'Conflict', count: stats.conflict_samples, color: '#FFD500' },
		{ key: 'unreviewed', label: 'Unreviewed', count: stats.unreviewed_samples, color: '#E2E0DB' },
	]}
	<div class="mb-5 border border-border bg-surface">
		<!-- Stacked bar -->
		<div class="flex h-2">
			{#each segments as seg}
				{@const pct = (seg.count / stats.total_samples) * 100}
				{#if pct > 0}
					<button
						onclick={() => setStatusFilter(seg.key)}
						class="h-full transition-opacity {filterStatus && filterStatus !== seg.key ? 'opacity-30' : ''}"
						style="width: {pct}%; background-color: {seg.color};"
						title="{seg.label}: {seg.count}"
					></button>
				{/if}
			{/each}
		</div>
		<!-- Legend -->
		<div class="flex flex-wrap items-center gap-4 px-4 py-2.5">
			{#each segments as seg}
				{#if seg.count > 0}
					<button
						onclick={() => setStatusFilter(seg.key)}
						class="flex items-center gap-1.5 text-xs transition-opacity {filterStatus && filterStatus !== seg.key ? 'opacity-40' : ''} hover:opacity-100"
					>
						<span class="inline-block h-2.5 w-2.5 shrink-0" style="background-color: {seg.color};"></span>
						<span class="font-medium text-text">{seg.count.toLocaleString()}</span>
						<span class="text-text-muted">{seg.label}</span>
					</button>
				{/if}
			{/each}
			<span class="ml-auto text-xs text-text-muted">{stats.total_samples.toLocaleString()} total</span>
		</div>
	</div>
{/if}

<div class="flex gap-5">
	<!-- Sidebar filters -->
	<aside class="w-48 shrink-0">
		<div class="sticky top-20 space-y-1">
			{#if hasActiveFilters}
				<button onclick={clearFilters} class="flex items-center gap-1 text-xs text-primary hover:underline">
					<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
						<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
					</svg>
					Clear all filters
				</button>
			{/if}

			<FilterGroup
				title="Scope"
				storageKey="scope"
				active={filterScope === 'mine'}
				activeLabel={filterScope === 'mine' ? 'Mine' : null}
			>
				<ul class="space-y-0.5">
					<li>
						<button
							onclick={() => setScope('all')}
							class="w-full px-2 py-1 text-left text-xs {filterScope === 'all' ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
						>
							All samples
						</button>
					</li>
					<li>
						<button
							onclick={() => setScope('mine')}
							class="w-full px-2 py-1 text-left text-xs {filterScope === 'mine' ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
						>
							My samples
						</button>
					</li>
				</ul>
			</FilterGroup>

			<FilterGroup
				title="Kind"
				storageKey="kind"
				active={!!filterKind}
				activeLabel={filterKind ? (filterKind === 'regular' ? 'Regular' : 'Condition') : null}
			>
				<ul class="space-y-0.5">
					{#each [
						{ key: '', label: 'All' },
						{ key: 'regular', label: 'Regular' },
						{ key: 'condition', label: 'Condition' },
					] as item}
						<li>
							<button
								onclick={() => setFilterValue('kind', item.key)}
								class="w-full px-2 py-1 text-left text-xs {filterKind === item.key ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								{item.label}
							</button>
						</li>
					{/each}
				</ul>
			</FilterGroup>

			<FilterGroup
				title="Annotation"
				storageKey="annotated"
				active={filterAnnotated === 'all' || filterAnnotated === 'raw'}
				activeLabel={filterAnnotated === 'all' ? 'All' : filterAnnotated === 'raw' ? 'Raw' : null}
			>
				<ul class="space-y-0.5">
					{#each [
						// Empty URL state defaults to 'teacher' on the server, so
						// highlight Teacher pass for both '' and 'teacher'.
						{ key: 'teacher', label: 'Teacher pass (default)', active: filterAnnotated === '' || filterAnnotated === 'teacher' },
						{ key: 'all', label: 'All (incl. raw)', active: filterAnnotated === 'all' },
						{ key: 'raw', label: 'Raw only (pending)', active: filterAnnotated === 'raw' },
					] as item}
						<li>
							<button
								onclick={() => setFilterValue('annotated', item.key === 'teacher' ? '' : item.key)}
								class="w-full px-2 py-1 text-left text-xs {item.active ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								{item.label}
							</button>
						</li>
					{/each}
				</ul>
			</FilterGroup>

			<FilterGroup
				title="Exposure"
				storageKey="exposure"
				active={!!filterExposure && filterExposure !== 'not_under'}
				activeLabel={filterExposure === 'under' ? 'Underexposed' : filterExposure === 'over' ? 'Overexposed' : filterExposure === 'normal' ? 'Normal' : filterExposure === 'all' ? 'All' : null}
			>
				<ul class="space-y-0.5">
					{#each [
						// Empty URL state → server applies 'not_under', so highlight
						// "Hide underexposed (default)" for both '' and explicit
						// 'not_under'.
						{ key: '', label: 'Hide underexposed (default)', active: filterExposure === '' || filterExposure === 'not_under' },
						{ key: 'all', label: 'All (incl. dark)', active: filterExposure === 'all' },
						{ key: 'under', label: 'Underexposed only', active: filterExposure === 'under' },
						{ key: 'normal', label: 'Normal only', active: filterExposure === 'normal' },
						{ key: 'over', label: 'Overexposed only', active: filterExposure === 'over' },
					] as item}
						<li>
							<button
								onclick={() => setFilterValue('exposure', item.key)}
								class="w-full px-2 py-1 text-left text-xs {item.active ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								{item.label}
							</button>
						</li>
					{/each}
				</ul>
			</FilterGroup>

			{#if auth.isReviewer}
				<FilterGroup
					title="My review"
					storageKey="my_review"
					active={!!filterMyReview}
					activeLabel={filterMyReview ? (MY_REVIEW_LABELS[filterMyReview] ?? filterMyReview) : null}
				>
					<ul class="space-y-0.5">
						{#each [
							{ key: '', label: 'All' },
							{ key: 'unreviewed', label: 'Not by me yet' },
							{ key: 'reviewed', label: 'By me (any)' },
							{ key: 'accepted', label: 'I accepted' },
							{ key: 'rejected', label: 'I rejected' },
						] as item}
							<li>
								<button
									onclick={() => setFilterValue('my_review', item.key)}
									class="w-full px-2 py-1 text-left text-xs {filterMyReview === item.key ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
								>
									{item.label}
								</button>
							</li>
						{/each}
					</ul>
				</FilterGroup>
			{/if}

			<FilterGroup
				title="Status (global)"
				storageKey="status"
				active={!!filterStatus}
				activeLabel={filterStatus ? (STATUS_LABELS[filterStatus] ?? filterStatus) : null}
			>
				<ul class="space-y-0.5">
					{#each [
						{ key: '', label: 'All' },
						{ key: 'unreviewed', label: 'Unreviewed' },
						{ key: 'in_review', label: 'In Review' },
						{ key: 'accepted', label: 'Accepted' },
						{ key: 'rejected', label: 'Rejected' },
						{ key: 'conflict', label: 'Conflict' },
					] as item}
						<li>
							<button
								onclick={() => setFilterValue('review_status', item.key)}
								class="w-full px-2 py-1 text-left text-xs {filterStatus === item.key ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								{item.label}
							</button>
						</li>
					{/each}
				</ul>
			</FilterGroup>

			{#if auth.user?.role === 'admin' && machines.length > 0}
				{@const activeMachine = filterMachine ? machines.find((m) => String(m.id) === filterMachine) : null}
				<FilterGroup
					title="Machine"
					storageKey="machine"
					active={!!filterMachine}
					activeLabel={activeMachine?.name ?? (filterMachine ? 'Selected' : null)}
				>
					<ul class="space-y-0.5">
						<li>
							<button
								onclick={() => updateMachineFilter('')}
								class="w-full px-2 py-1 text-left text-xs {filterMachine === '' ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								All
							</button>
						</li>
						{#each machineGroups as group (group.ownerKey)}
							{#if filterScope === 'all'}
								<li class="px-2 pt-2 text-[10px] uppercase tracking-wider text-text-muted">
									{group.ownerLabel}
								</li>
							{/if}
							{#each group.machines as machine (machine.id)}
								<li>
									<button
										onclick={() => updateMachineFilter(String(machine.id))}
										class="w-full truncate px-2 py-1 text-left text-xs {filterMachine === String(machine.id) ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
										title={machine.owner?.display_name ? `${machine.owner.display_name} / ${machine.name}` : machine.name}
									>
										{machine.name}
									</button>
								</li>
							{/each}
						{/each}
					</ul>
				</FilterGroup>
			{/if}

			{#if filterOptions.source_roles.length > 0}
				<FilterGroup
					title="Source"
					storageKey="source_role"
					active={!!filterSourceRole}
					activeLabel={filterSourceRole ? sourceRoleLabel(filterSourceRole) : null}
				>
					<ul class="space-y-0.5">
						<li>
							<button
								onclick={() => updateSourceRoleFilter('')}
								class="flex w-full items-center gap-2 px-2 py-1 text-left text-xs {filterSourceRole === '' ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								<span class="min-w-0 flex-1 truncate">All</span>
								<span class="tabular-nums text-[10px] text-text-muted">{totalSourceRoleCount().toLocaleString()}</span>
							</button>
						</li>
						{#each filterOptions.source_roles as sourceRole (sourceRole)}
							<li>
								<button
									onclick={() => updateSourceRoleFilter(sourceRole)}
									class="flex w-full items-center gap-2 px-2 py-1 text-left text-xs {filterSourceRole === sourceRole ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
								>
									<span class="min-w-0 flex-1 truncate">{sourceRoleLabel(sourceRole)}</span>
									<span class="tabular-nums text-[10px] text-text-muted">{sourceRoleCount(sourceRole).toLocaleString()}</span>
								</button>
							</li>
						{/each}
					</ul>
				</FilterGroup>
			{/if}

			<FilterGroup
				title="Age"
				storageKey="age"
				active={!!filterMaxAgeHours}
				activeLabel={filterMaxAgeHours ? (AGE_OPTIONS.find((o) => o.value === filterMaxAgeHours)?.label ?? null) : null}
			>
				<ul class="space-y-0.5">
					{#each AGE_OPTIONS as opt (opt.value)}
						<li>
							<button
								onclick={() => updateAgeFilter(opt.value)}
								class="w-full px-2 py-1 text-left text-xs {filterMaxAgeHours === opt.value ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								{opt.label}
							</button>
						</li>
					{/each}
				</ul>
			</FilterGroup>

			{#if auth.user?.role === 'admin'}
				<FilterGroup
					title="Archived"
					storageKey="archived"
					active={!!filterArchived}
					activeLabel={filterArchived === 'archived' ? 'Archived only' : filterArchived === 'all' ? 'Both' : null}
				>
					<ul class="space-y-0.5">
						{#each [
							{ key: '', label: 'Active only' },
							{ key: 'archived', label: 'Archived only' },
							{ key: 'all', label: 'Both' },
						] as item}
							<li>
								<button
									onclick={() => setFilterValue('archived', item.key)}
									class="w-full px-2 py-1 text-left text-xs {filterArchived === item.key ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
								>
									{item.label}
								</button>
							</li>
						{/each}
					</ul>
				</FilterGroup>
			{/if}
		</div>
	</aside>

	<!-- Main content -->
	<div class="min-w-0 flex-1">
		{#if loading}
			<Spinner />
		{:else if !data || data.items.length === 0}
			<div class="border border-border bg-surface px-6 py-12 text-center">
				<svg class="mx-auto mb-3 h-10 w-10 text-border" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
					<path stroke-linecap="square" stroke-linejoin="miter" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5a1.5 1.5 0 0 0 1.5-1.5V4.5a1.5 1.5 0 0 0-1.5-1.5H3.75a1.5 1.5 0 0 0-1.5 1.5v15a1.5 1.5 0 0 0 1.5 1.5z" />
				</svg>
				<p class="text-sm text-text-muted">
					{#if hasActiveFilters}
						No samples match your current filters.
					{:else}
						No samples yet. Samples appear here once a machine starts capturing.
					{/if}
				</p>
				{#if hasActiveFilters}
					<button onclick={clearFilters} class="mt-2 text-xs text-primary hover:underline">Clear filters</button>
				{/if}
			</div>
		{:else}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
				{#each data.items as sample (sample.id)}
					<SampleCard {sample} href={`/samples/${sample.id}${filterContextQuery}`} />
				{/each}
			</div>

			<!-- Pagination -->
			{#if data.pages > 1}
				<div class="mt-6 flex items-center justify-between border border-border bg-surface px-4 py-2.5">
					<div class="flex items-center gap-3">
						<span class="text-xs text-text-muted">{(data.page - 1) * pageSize + 1}–{Math.min(data.page * pageSize, data.total)} of {data.total.toLocaleString()}</span>
						<select
							value={pageSize}
							onchange={(e) => changePageSize(Number((e.currentTarget as HTMLSelectElement).value))}
							class="border border-border bg-surface px-2 py-1 text-xs text-text focus:border-primary focus:outline-none"
						>
							<option value={10}>10 / page</option>
							<option value={20}>20 / page</option>
							<option value={30}>30 / page</option>
							<option value={50}>50 / page</option>
							<option value={100}>100 / page</option>
						</select>
					</div>
					<div class="flex items-center gap-1">
						<button
							onclick={() => goToPage(currentPage - 1)}
							disabled={currentPage <= 1}
							class="border border-border px-3 py-1.5 text-xs font-medium text-text hover:bg-bg disabled:opacity-30"
						>
							Previous
						</button>
						{#each Array.from({ length: data.pages }, (_, i) => i + 1) as p}
							{#if data.pages <= 7 || p === 1 || p === data.pages || (p >= currentPage - 1 && p <= currentPage + 1)}
								<button
									onclick={() => goToPage(p)}
									class="min-w-[32px] px-2.5 py-1.5 text-xs font-medium {p === currentPage ? 'bg-primary text-white' : 'text-text hover:bg-bg'}"
								>
									{p}
								</button>
							{:else if p === 2 || p === data.pages - 1}
								<span class="px-1 text-text-muted">...</span>
							{/if}
						{/each}
						<button
							onclick={() => goToPage(currentPage + 1)}
							disabled={currentPage >= data.pages}
							class="border border-border px-3 py-1.5 text-xs font-medium text-text hover:bg-bg disabled:opacity-30"
						>
							Next
						</button>
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>
