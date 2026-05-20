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
		filterMachine || filterStatus || filterSourceRole || filterCaptureReason || filterMaxAgeHours
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

	const currentTeacherFilter = $derived<TeacherJobFilter>({
		scope: filterScope,
		machine_id: filterMachine || undefined,
		review_status: filterStatus || undefined,
		source_role: filterSourceRole || undefined,
		capture_reason: filterCaptureReason || undefined,
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
				if (filterMaxAgeHours) sp.set('max_age_hours', filterMaxAgeHours);
				// review_status filter doesn't make sense — the queue only serves unreviewed
				// + in_review samples anyway.
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
	<div class="mb-5 border border-border bg-white">
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
		<div class="sticky top-20 space-y-5">
			{#if hasActiveFilters}
				<button onclick={clearFilters} class="flex items-center gap-1 text-xs text-primary hover:underline">
					<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
						<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
					</svg>
					Clear all filters
				</button>
			{/if}

			<!-- Scope -->
			<div>
				<h3 class="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Scope</h3>
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
			</div>

			<!-- Status -->
			<div>
				<h3 class="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Status</h3>
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
			</div>

			<!-- Machine — admin-only for now: members shouldn't be able to filter/browse by
				 individual rigs (exposes other users' rig names + owners when scope=all). -->
			{#if auth.user?.role === 'admin' && machines.length > 0}
				<div>
					<h3 class="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Machine</h3>
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
				</div>
			{/if}

			<!-- Source -->
			{#if filterOptions.source_roles.length > 0}
				<div>
					<h3 class="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Source</h3>
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
				</div>
			{/if}

			<!-- Age (upload time) -->
			<div>
				<h3 class="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Age</h3>
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
			</div>
		</div>
	</aside>

	<!-- Main content -->
	<div class="min-w-0 flex-1">
		{#if loading}
			<Spinner />
		{:else if !data || data.items.length === 0}
			<div class="border border-border bg-white px-6 py-12 text-center">
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
				<div class="mt-6 flex items-center justify-between border border-border bg-white px-4 py-2.5">
					<div class="flex items-center gap-3">
						<span class="text-xs text-text-muted">{(data.page - 1) * pageSize + 1}–{Math.min(data.page * pageSize, data.total)} of {data.total.toLocaleString()}</span>
						<select
							value={pageSize}
							onchange={(e) => changePageSize(Number((e.currentTarget as HTMLSelectElement).value))}
							class="border border-border bg-white px-2 py-1 text-xs text-text focus:border-primary focus:outline-none"
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
