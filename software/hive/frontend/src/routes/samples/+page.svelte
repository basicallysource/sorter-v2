<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type Machine,
		type SampleFilterOptions,
		type StatsOverview,
		type TeacherJobFilter,
		type TeacherJobSummary
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Button from '$lib/components/Button.svelte';
	import FilterGroup from '$lib/components/FilterGroup.svelte';
	import FilterOption from '$lib/components/FilterOption.svelte';
	import MachineFilter from '$lib/components/MachineFilter.svelte';
	import ReviewGrid from '$lib/components/ReviewGrid.svelte';
	import SampleCard from '$lib/components/SampleCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Menu from '$lib/components/Menu.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Archive from '@lucide/svelte/icons/archive';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ChartColumn from '@lucide/svelte/icons/chart-column';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import Images from '@lucide/svelte/icons/images';
	import ListChecks from '@lucide/svelte/icons/list-checks';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';
	import { readSampleFilters, sampleFiltersQuery, sampleQueue } from '$lib/sampleListContext';
	import { writeMachines } from '$lib/reviewQueue.svelte';

	let machines = $state<Machine[]>([]);
	let filterOptions = $state<SampleFilterOptions>({ source_roles: [], capture_reasons: [] });
	let stats = $state<StatsOverview | null>(null);

	// Filters are derived from the URL so reload / share preserves them.
	const listContext = $derived(readSampleFilters(page.url.searchParams));
	// One queue per set of filters, shared with the sample detail page: a new
	// filter is a new queue, and nothing still on its way for the old one can
	// reach this grid.
	const queue = $derived(sampleQueue(listContext));
	// Default scope is "all" — the URL value is only honored when it is the explicit opt-in to
	// "mine". Anything else (missing/empty/other) collapses to all, so a stray query param can't
	// accidentally limit the view.
	const filterScope = $derived(listContext.scope === 'mine' ? 'mine' : 'all');
	// One machine or several; none means every machine.
	const filterMachines = $derived(listContext.machine_ids);
	const machineNames = $derived(
		filterMachines.map((id) => machines.find((m) => String(m.id) === id)?.name ?? id).join(', ')
	);
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
		in_review: 'Needs more reviews',
		accepted: 'Accepted',
		rejected: 'Rejected',
		conflict: 'Conflict'
	};
	// Histogram bucket — 'under' / 'normal' / 'over' / 'all'. Empty = no filter.
	const filterExposure = $derived(listContext.exposure ?? '');
	// Is the colour reference palette in view, as the swatch model called it:
	// 'in_view' / 'not_in_view' / 'unchecked' (not called yet). Empty = any.
	const filterPalette = $derived(listContext.palette ?? '');
	const PALETTE_LABELS: Record<string, string> = {
		in_view: 'In view',
		not_in_view: 'Not in view',
		unchecked: 'Not checked yet'
	};
	// Admin-only: 'active' (default), 'archived', 'all'. Server enforces:
	// non-admins always see active regardless of what they send.
	const filterArchived = $derived(listContext.archived ?? '');
	const filterMaxAgeHours = $derived(listContext.max_age_hours ?? '');

	const AGE_OPTIONS: { value: string; label: string }[] = [
		{ value: '', label: 'All' },
		{ value: '24', label: 'Last 24h' },
		{ value: '168', label: 'Last 7 days' },
		{ value: '720', label: 'Last 30 days' }
	];

	const filterContextQuery = $derived(sampleFiltersQuery(page.url.searchParams));

	const sourceRoleLabels: Record<string, string> = {
		c_channel_1: 'C1',
		c_channel_2: 'C2',
		c_channel_3: 'C3',
		classification_channel: 'C-channel 4, classification',
		classification_chamber: 'Classification chamber',
		carousel: 'Carousel',
		piece_crop: 'Piece crop',
		top: 'Top camera',
		bottom: 'Bottom camera'
	};

	const hasActiveFilters = $derived(
		filterMachines.length > 0 || filterStatus || filterSourceRole || filterCaptureReason || filterKind || filterMyReview || filterAnnotated || filterExposure || filterPalette || filterArchived || filterMaxAgeHours
	);

	const machinesKey = $derived(filterMachines.join(','));
	$effect(() => {
		void loadFilters(filterScope, machinesKey ? machinesKey.split(',') : []);
	});

	// Load the list for the current filters (a queue already loaded for them,
	// say on coming back from a sample, is kept as it is).
	$effect(() => {
		void queue.start();
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

	function setFilterValue(key: string, value: string) {
		pushFilterUrl((sp) => {
			if (value) sp.set(key, value);
			else sp.delete(key);
		});
	}

	// Machines, filter options and the status counts (worker-kept, so cheap);
	// only the newest answer is shown.
	let filtersToken = 0;
	async function loadFilters(scope: 'mine' | 'all', machineIds: string[]) {
		const token = ++filtersToken;
		try {
			const [nextMachines, nextOptions, nextStats] = await Promise.all([
				api.getMachines({ scope }),
				api.getSampleFilterOptions({ scope }),
				api.getOverview({ scope, machineIds })
			]);
			if (token !== filtersToken) return;
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
			writeMachines(sp, []);
		});
	}

	function updateMachineFilter(ids: string[]) {
		pushFilterUrl((sp) => writeMachines(sp, ids));
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
			writeMachines(sp, []);
			sp.delete('review_status');
			sp.delete('source_role');
			sp.delete('capture_reason');
			sp.delete('kind');
			sp.delete('my_review');
			sp.delete('annotated');
			sp.delete('exposure');
			sp.delete('palette');
			sp.delete('archived');
			sp.delete('max_age_hours');
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
		machine_ids: filterMachines,
		source_role: filterSourceRole || undefined,
		capture_reason: filterCaptureReason || undefined,
		review_status: filterStatus || undefined,
		kind: filterKind || undefined,
		my_review: filterMyReview || undefined,
		annotated: filterAnnotated || undefined,
		// Mirror the server-side default ('normal' = good light only) so a
		// "Delete / Archive filtered" from the default view operates on
		// exactly the samples the operator can see — not on under/over
		// frames that are hidden by default.
		exposure: filterExposure || 'normal',
		palette: filterPalette || undefined,
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
			await queue.reload();
			await loadFilters(filterScope, filterMachines);
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
		machine_ids: filterMachines,
		source_role: filterSourceRole || undefined,
		capture_reason: filterCaptureReason || undefined,
		review_status: filterStatus || undefined,
		kind: filterKind || undefined,
		my_review: filterMyReview || undefined,
		annotated: filterAnnotated || undefined,
		// Mirror the server-side default ('normal' = good light only) so a
		// "Delete / Archive filtered" from the default view operates on
		// exactly the samples the operator can see — not on under/over
		// frames that are hidden by default.
		exposure: filterExposure || 'normal',
		palette: filterPalette || undefined,
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
			await queue.reload();
			await loadFilters(filterScope, filterMachines);
		} catch (e) {
			archiveError = e instanceof Error ? e.message : 'Archive failed.';
		} finally {
			archiveRunning = false;
		}
	}

	const currentTeacherFilter = $derived<TeacherJobFilter>({
		scope: filterScope,
		machine_ids: filterMachines,
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
		palette: filterPalette || undefined,
		// Age filter must travel with the job filter — otherwise the modal counts a 24h
		// slice but the job picks up the full table.
		max_age_hours: filterMaxAgeHours ? Number(filterMaxAgeHours) : undefined
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
					await queue.reload();
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
		if (!Number.isFinite(seconds) || seconds < 0) return '-';
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
			startedAtLabel: new Date(job.started_at).toLocaleTimeString('en-US', {
				hour: '2-digit', minute: '2-digit'
			})
		};
	}

	$effect(() => {
		return () => stopTeacherPolling();
	});

	function formatUsd(value: number): string {
		if (value === 0) return '$0.00';
		return Math.abs(value) < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
	}
</script>

<svelte:head>
	<title>Samples - Hive</title>
</svelte:head>

{#snippet activeFilter(withScope: boolean)}
	{#if hasActiveFilters}
		<div class="rounded-control bg-well p-3">
			<div class="mb-2 text-sm text-ink-muted">The filter</div>
			<div class="flex flex-wrap gap-1.5">
				{#each [
					withScope && filterScope === 'mine' ? ['Scope', 'mine'] : null,
					filterMachines.length > 0 ? ['Machine', machineNames] : null,
					filterSourceRole ? ['Source', filterSourceRole] : null,
					filterCaptureReason ? ['Capture reason', filterCaptureReason] : null,
					filterStatus ? ['Status', filterStatus] : null,
					filterKind ? ['Kind', filterKind] : null,
					filterMyReview ? ['My review', filterMyReview] : null,
					filterAnnotated ? ['Annotation', filterAnnotated] : null,
					filterExposure ? ['Exposure', filterExposure] : null,
					filterMaxAgeHours ? ['Newer than hours', filterMaxAgeHours] : null
				].filter((c): c is string[] => c !== null) as [name, value] (name)}
					<Badge>{name} <span class="font-mono text-ink">{value}</span></Badge>
				{/each}
			</div>
		</div>
	{/if}
{/snippet}

<PageHeader title="Samples" description="Browse and review the training samples your machines capture.">
	{#snippet actions()}
		<Button href="/samples/diversity" icon={ChartColumn}>Diversity</Button>
		{#if auth.user?.role === 'admin' || filterScope === 'mine'}
			<Menu
				label="Sample actions"
				items={[
					...(auth.user?.role === 'admin'
						? [
								{ label: 'Teacher jobs', icon: ListChecks, href: '/admin/teacher-jobs' },
								{ label: 'Re-run the teacher', icon: Sparkles, onselect: openTeacherModal },
								{
									label: filterArchived === 'archived' ? 'Unarchive the filtered samples' : 'Archive the filtered samples',
									icon: Archive,
									onselect: () => openArchiveModal(filterArchived === 'archived' ? 'unarchive' : 'archive')
								}
							]
						: []),
					...(filterScope === 'mine'
						? [
								'separator' as const,
								{
									label: hasActiveFilters ? 'Delete the filtered samples' : 'Delete all my samples',
									icon: Trash2,
									danger: true,
									onselect: openDeleteModal
								}
							]
						: [])
				]}
			>
				{#snippet trigger(props)}
					<Button {...props} icon={Ellipsis} label="More actions" />
				{/snippet}
			</Menu>
		{/if}
		{#if auth.isReviewer}
			<!-- The review queue gets the same filters, so it drains the slice shown here. -->
			{@const reviewHref = `/review${filterContextQuery}`}
			<Button
				href={reviewHref}
				variant="primary"
				icon={CircleCheck}
				title={hasActiveFilters ? 'Review only the samples the filter shows' : 'Open the whole review queue'}
				>{hasActiveFilters ? 'Review filtered' : 'Review samples'}</Button
			>
		{/if}
	{/snippet}
</PageHeader>

{#if teacherJob}
	{@const job = teacherJob}
	{@const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0}
	{@const eta = computeEta(job)}
	<Panel flush>
		<div class="flex flex-wrap items-center gap-x-3 gap-y-2 px-(--pad-panel) py-3 text-sm">
			<span class="font-medium text-ink">Teacher job</span>
			<Badge>{sentence(job.status)}</Badge>
			<span class="font-mono text-ink-muted">{job.openrouter_model}</span>
			<span class="num text-ink">{job.processed} of {job.total}</span>
			<span class="num text-ink-muted">{job.succeeded} succeeded{job.failed > 0 ? `, ${job.failed} failed` : ''}</span>
			<span class="num text-ink-muted" title="Billed so far, and the total at the average cost a sample.">
				{formatUsd(job.cost_usd)}{#if job.cost_usd_estimated_total != null && (job.status === 'pending' || job.status === 'running')},
					about {formatUsd(job.cost_usd_estimated_total)} in all{/if}
			</span>
			{#if eta}
				<span class="num text-ink-muted" title={`At ${eta.rate.toFixed(2)} a second since ${eta.startedAtLabel}.`}
					>{eta.remainingLabel} left</span
				>
			{/if}
			<div class="ml-auto flex flex-wrap items-center gap-2">
				<Button size="sm" variant="ghost" href={`/admin/teacher-jobs/${job.id}`} icon={ArrowRight}>Details</Button>
				{#if job.status === 'pending' || job.status === 'running'}
					<Button size="sm" onclick={cancelTeacherJob}>Cancel</Button>
				{:else}
					<Button size="sm" variant="ghost" onclick={dismissTeacherJob}>Dismiss</Button>
				{/if}
			</div>
		</div>
		<div class="px-(--pad-panel) pb-3"><ProgressBar label="Teacher job progress" value={pct} /></div>
		{#if job.last_error}
			<div class="px-(--pad-panel) pb-3"><Alert tone="warning" title="Last error">{job.last_error}</Alert></div>
		{/if}
	</Panel>
{/if}

{#if stats && stats.total_samples > 0}
	{@const segments = [
		{ key: 'accepted', label: 'Accepted', count: stats.accepted_samples, color: 'var(--success)' },
		{ key: 'rejected', label: 'Rejected', count: stats.rejected_samples, color: 'var(--danger)' },
		{ key: 'in_review', label: 'Needs more reviews', count: stats.in_review_samples, color: 'var(--info)' },
		{ key: 'conflict', label: 'Conflict', count: stats.conflict_samples, color: 'var(--warning)' },
		{ key: 'unreviewed', label: 'Unreviewed', count: stats.unreviewed_samples, color: 'var(--line-strong)' }
	]}
	<Panel flush>
		<div class="flex h-2">
			{#each segments as seg (seg.key)}
				{@const share = (seg.count / stats.total_samples) * 100}
				{#if share > 0}
					<button
						type="button"
						onclick={() => setStatusFilter(seg.key)}
						class="h-full transition-opacity {filterStatus && filterStatus !== seg.key ? 'opacity-30' : ''}"
						style="width: {share}%; background-color: {seg.color};"
						title="{seg.label}: {seg.count}"
						aria-label="Show {seg.label}"
					></button>
				{/if}
			{/each}
		</div>
		<div class="flex flex-wrap items-center gap-x-4 gap-y-1 px-(--pad-panel) py-2.5">
			{#each segments as seg (seg.key)}
				{#if seg.count > 0}
					<button
						type="button"
						onclick={() => setStatusFilter(seg.key)}
						class="flex items-center gap-1.5 text-sm transition-opacity hover:opacity-100 {filterStatus && filterStatus !== seg.key
							? 'opacity-40'
							: ''}"
					>
						<span class="size-2.5 shrink-0 rounded-full" style="background-color: {seg.color};"></span>
						<span class="num font-medium text-ink">{seg.count.toLocaleString()}</span>
						<span class="text-ink-muted">{seg.label}</span>
					</button>
				{/if}
			{/each}
			<span class="num ml-auto text-sm text-ink-muted">{stats.total_samples.toLocaleString()} in all</span>
		</div>
	</Panel>
{/if}

<div class="flex flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
	<!-- The filters: a column on a surface beside the grid; above it on a narrow screen. -->
	<aside class="w-full shrink-0 lg:sticky lg:top-(--size-topbar) lg:w-56 lg:pt-0">
		<div class="overflow-hidden rounded-panel bg-surface">
			{#if hasActiveFilters}
				<div class="px-1.5 pt-1.5">
					<Button size="sm" variant="ghost" icon={X} onclick={clearFilters}>Clear the filters</Button>
				</div>
			{/if}
			<div class="flex flex-col divide-y divide-line py-1">
				<FilterGroup title="Scope" storageKey="scope" active={filterScope === 'mine'} activeLabel={filterScope === 'mine' ? 'Mine' : null}>
					<ul class="flex flex-col gap-px">
						<FilterOption label="All samples" on={filterScope === 'all'} onclick={() => setScope('all')} />
						<FilterOption label="My samples" on={filterScope === 'mine'} onclick={() => setScope('mine')} />
					</ul>
				</FilterGroup>

				<FilterGroup
					title="Kind"
					storageKey="kind"
					active={!!filterKind}
					activeLabel={filterKind === 'regular' ? 'Detection' : filterKind === 'condition' ? 'Condition' : null}
				>
					<ul class="flex flex-col gap-px">
						{#each [
							{ key: '', label: 'All' },
							{ key: 'regular', label: 'Detection' },
							{ key: 'condition', label: 'Condition' }
						] as item (item.key)}
							<FilterOption label={item.label} on={filterKind === item.key} onclick={() => setFilterValue('kind', item.key)} />
						{/each}
					</ul>
				</FilterGroup>

				<FilterGroup
					title="Annotation"
					storageKey="annotated"
					active={filterAnnotated === 'all' || filterAnnotated === 'raw'}
					activeLabel={filterAnnotated === 'all' ? 'All' : filterAnnotated === 'raw' ? 'Raw' : null}
				>
					<!-- An empty value means the server's default, the teacher pass. -->
					<ul class="flex flex-col gap-px">
						<FilterOption label="Teacher pass" on={filterAnnotated === '' || filterAnnotated === 'teacher'} onclick={() => setFilterValue('annotated', '')} />
						<FilterOption label="All, with raw" on={filterAnnotated === 'all'} onclick={() => setFilterValue('annotated', 'all')} />
						<FilterOption label="Raw only, waiting" on={filterAnnotated === 'raw'} onclick={() => setFilterValue('annotated', 'raw')} />
					</ul>
				</FilterGroup>

				<FilterGroup
					title="Exposure"
					storageKey="exposure"
					active={filterExposure === 'under' || filterExposure === 'over'}
					activeLabel={filterExposure === 'under' ? 'Dark' : filterExposure === 'over' ? 'Bright' : null}
				>
					<!-- An empty value means the server's default, good light. -->
					<ul class="flex flex-col gap-px">
						<FilterOption label="Good light" on={filterExposure === '' || filterExposure === 'normal'} onclick={() => setFilterValue('exposure', '')} />
						<FilterOption label="Underexposed" on={filterExposure === 'under'} onclick={() => setFilterValue('exposure', 'under')} />
						<FilterOption label="Overexposed" on={filterExposure === 'over'} onclick={() => setFilterValue('exposure', 'over')} />
					</ul>
				</FilterGroup>

				<FilterGroup
					title="Color palette"
					storageKey="palette"
					active={!!filterPalette}
					activeLabel={filterPalette ? (PALETTE_LABELS[filterPalette] ?? filterPalette) : null}
				>
					<!-- The reference palette's tiles at the edge of a classification frame, as the swatch model called it. -->
					<ul class="flex flex-col gap-px">
						{#each [
							{ key: '', label: 'Any' },
							{ key: 'in_view', label: 'In view' },
							{ key: 'not_in_view', label: 'Not in view' },
							{ key: 'unchecked', label: 'Not checked yet' }
						] as item (item.key)}
							<FilterOption label={item.label} on={filterPalette === item.key} onclick={() => setFilterValue('palette', item.key)} />
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
						<ul class="flex flex-col gap-px">
							{#each [
								{ key: '', label: 'All' },
								{ key: 'unreviewed', label: 'Not reviewed by me' },
								{ key: 'reviewed', label: 'Reviewed by me' },
								{ key: 'accepted', label: 'I accepted' },
								{ key: 'rejected', label: 'I rejected' }
							] as item (item.key)}
								<FilterOption label={item.label} on={filterMyReview === item.key} onclick={() => setFilterValue('my_review', item.key)} />
							{/each}
						</ul>
					</FilterGroup>
				{/if}

				<FilterGroup
					title="Status, everyone's"
					storageKey="status"
					active={!!filterStatus}
					activeLabel={filterStatus ? (STATUS_LABELS[filterStatus] ?? filterStatus) : null}
				>
					<ul class="flex flex-col gap-px">
						{#each [
							{ key: '', label: 'All' },
							{ key: 'unreviewed', label: 'Unreviewed' },
							{ key: 'in_review', label: 'Needs more reviews' },
							{ key: 'accepted', label: 'Accepted' },
							{ key: 'rejected', label: 'Rejected' },
							{ key: 'conflict', label: 'Conflict' }
						] as item (item.key)}
							<FilterOption label={item.label} on={filterStatus === item.key} onclick={() => setFilterValue('review_status', item.key)} />
						{/each}
					</ul>
				</FilterGroup>

				{#if machines.length > 1}
					<MachineFilter {machines} selected={filterMachines} onchange={updateMachineFilter} />
				{/if}

				{#if filterOptions.source_roles.length > 0}
					<FilterGroup
						title="Source"
						storageKey="source_role"
						active={!!filterSourceRole}
						activeLabel={filterSourceRole ? sourceRoleLabel(filterSourceRole) : null}
					>
						<ul class="flex flex-col gap-px">
							<FilterOption label="All" on={filterSourceRole === ''} onclick={() => updateSourceRoleFilter('')} count={totalSourceRoleCount()} />
							{#each filterOptions.source_roles as sourceRole (sourceRole)}
								<FilterOption label={sourceRoleLabel(sourceRole)} on={filterSourceRole === sourceRole} onclick={() => updateSourceRoleFilter(sourceRole)} count={sourceRoleCount(sourceRole)} />
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
					<ul class="flex flex-col gap-px">
						{#each AGE_OPTIONS as opt (opt.value)}
							<FilterOption label={opt.label} on={filterMaxAgeHours === opt.value} onclick={() => updateAgeFilter(opt.value)} />
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
						<ul class="flex flex-col gap-px">
							{#each [
								{ key: '', label: 'Not archived' },
								{ key: 'archived', label: 'Archived only' },
								{ key: 'all', label: 'Both' }
							] as item (item.key)}
								<FilterOption label={item.label} on={filterArchived === item.key} onclick={() => setFilterValue('archived', item.key)} />
							{/each}
						</ul>
					</FilterGroup>
				{/if}
			</div>
		</div>
	</aside>

	<div class="flex min-w-0 flex-1 flex-col gap-3">
		<ReviewGrid
			{queue}
			gridClass="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
			emptyIcon={Images}
			emptyTitle={hasActiveFilters ? 'No samples match' : 'No samples to show'}
		>
			{#snippet empty()}
				{hasActiveFilters
					? 'Nothing matches the filters.'
					: 'Samples show here once the teacher has looked at them; the ones still waiting are under Annotation.'}
			{/snippet}
			{#snippet emptyAction()}
				{#if hasActiveFilters}<Button size="sm" onclick={clearFilters}>Clear the filters</Button>{/if}
			{/snippet}
			{#snippet item(sample)}
				<SampleCard {sample} href={`/samples/${sample.id}${filterContextQuery}`} />
			{/snippet}
		</ReviewGrid>
	</div>
</div>

<Modal
	open={archiveModalOpen}
	title={archiveMode === 'archive' ? 'Archive the filtered samples' : 'Unarchive the filtered samples'}
	onclose={closeArchiveModal}
>
	<div class="flex flex-col gap-4 text-sm">
		{#if archiveError}<Alert tone="danger">{archiveError}</Alert>{/if}
		{#if archiveResult}
			<p class="text-ink">
				{archiveResult.mode === 'archive' ? 'Archived' : 'Unarchived'}
				<span class="num font-medium">{archiveResult.archived}</span> sample{archiveResult.archived === 1 ? '' : 's'}.
			</p>
		{:else if archiveCount === null}
			<p class="flex items-center gap-2 text-ink-muted"><Spinner size={14} />Counting</p>
		{:else if archiveCount === 0}
			<p class="text-ink">No {archiveMode === 'archive' ? 'current' : 'archived'} samples match the filter.</p>
		{:else}
			<p class="text-ink">
				{#if archiveMode === 'archive'}
					Archive <span class="num font-medium">{archiveCount.toLocaleString()}</span> sample{archiveCount === 1 ? '' : 's'} that
					match the filter?
				{:else}
					Put <span class="num font-medium">{archiveCount.toLocaleString()}</span> archived sample{archiveCount === 1 ? '' : 's'}
					back in use?
				{/if}
			</p>
			<ul class="list-disc pl-5 text-ink-muted">
				{#if archiveMode === 'archive'}
					<li>They leave the sample list, the review queue and training.</li>
					<li>Their files and data stay; unarchive brings them back.</li>
					<li>Admins only, across the whole library.</li>
				{:else}
					<li>They come back to the lists, the review queue and training.</li>
					<li>Nothing else changes.</li>
				{/if}
			</ul>
			{@render activeFilter(true)}
			{#if !hasActiveFilters}
				<Alert tone="warning">
					No filter is on, so this {archiveMode === 'archive'
						? 'archives every sample in the library'
						: 'brings back every archived sample'}. Narrow it with the filters first for only some.
				</Alert>
			{/if}
			{#if archiveCapped}
				<Alert tone="warning">More than 20,000 match, the most one call takes. Narrow the filter and try again.</Alert>
			{/if}
		{/if}
	</div>
	{#snippet footer()}
		<Button variant="ghost" disabled={archiveRunning} onclick={closeArchiveModal}>{archiveResult ? 'Close' : 'Cancel'}</Button>
		{#if !archiveResult}
			<Button
				variant="primary"
				loading={archiveRunning}
				disabled={archiveCount === null || archiveCount === 0 || archiveCapped}
				onclick={runBatchArchive}
			>
				{#if archiveCount && archiveCount > 0}
					{archiveMode === 'archive' ? `Archive ${archiveCount.toLocaleString()}` : `Unarchive ${archiveCount.toLocaleString()}`}
				{:else}
					{archiveMode === 'archive' ? 'Archive' : 'Unarchive'}
				{/if}
			</Button>
		{/if}
	{/snippet}
</Modal>

<Modal open={deleteModalOpen} title="Delete the filtered samples" onclose={closeDeleteModal}>
	<div class="flex flex-col gap-4 text-sm">
		{#if deleteError}<Alert tone="danger">{deleteError}</Alert>{/if}
		{#if deleteResult}
			<p class="text-ink">
				Deleted <span class="num font-medium">{deleteResult.deleted}</span> sample{deleteResult.deleted === 1 ? '' : 's'}.
			</p>
		{:else if deleteCount === null}
			<p class="flex items-center gap-2 text-ink-muted"><Spinner size={14} />Counting</p>
		{:else if deleteCount === 0}
			<p class="text-ink">No samples match the filter.</p>
		{:else}
			<p class="text-ink">
				Delete <span class="num font-medium">{deleteCount.toLocaleString()}</span> of your samples that match the filter, for good?
			</p>
			<ul class="list-disc pl-5 text-ink-muted">
				<li>Their pictures, frames, overlays and annotations leave storage.</li>
				<li>It cannot be undone.</li>
				<li>Only your own samples are touched, even where the filter would match someone else's.</li>
			</ul>
			{@render activeFilter(false)}
			{#if !hasActiveFilters}
				<Alert tone="warning">No filter is on, so this deletes every sample you own. Narrow it with the filters first for only some.</Alert>
			{/if}
			{#if deleteCapped}
				<Alert tone="warning">More than 5,000 match, the most one call takes. Narrow the filter before deleting.</Alert>
			{/if}
		{/if}
	</div>
	{#snippet footer()}
		<Button variant="ghost" disabled={deleteRunning} onclick={closeDeleteModal}>{deleteResult ? 'Close' : 'Cancel'}</Button>
		{#if !deleteResult}
			<Button
				variant="danger"
				loading={deleteRunning}
				disabled={deleteCount === null || deleteCount === 0 || deleteCapped}
				onclick={runBatchDelete}>{deleteCount && deleteCount > 0 ? `Delete ${deleteCount.toLocaleString()}` : 'Delete'}</Button
			>
		{/if}
	{/snippet}
</Modal>

<Modal open={teacherModalOpen} title="Re-run the teacher" onclose={() => (teacherModalOpen = false)}>
	<div class="flex flex-col gap-4 text-sm">
		<p class="text-ink">
			Run the teacher over the samples that match the filter. Samples from a source with no prompt are skipped.
		</p>
		<ul class="list-disc pl-5 text-ink-muted">
			<li>It replaces <code class="font-mono">detection_bboxes</code>, <code class="font-mono">detection_count</code> and <code class="font-mono">detection_score</code>.</li>
			<li>It sets the review status back to unreviewed, so the new boxes are reviewed again.</li>
			<li>It uses the OpenRouter key in your settings.</li>
			<li>It runs at about one sample a second, to stay inside the model's rate limit.</li>
		</ul>
		{#if teacherError}<Alert tone="warning">{teacherError}</Alert>{/if}
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (teacherModalOpen = false)}>Cancel</Button>
		<Button variant="primary" loading={teacherSubmitting} onclick={submitTeacherJob}>Start the job</Button>
	{/snippet}
</Modal>
