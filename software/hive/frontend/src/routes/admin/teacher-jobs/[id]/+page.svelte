<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '$lib/auth.svelte';
	import { api, type TeacherJobDetail, type TeacherJobItemSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const REFRESH_MS = 3000;
	const PAGE_SIZE = 50;
	// Filter values mirror the backend's items_status enum + "all" (no filter).
	const FILTER_OPTIONS = ['all', 'queued', 'running', 'done', 'error', 'skipped'] as const;
	type ItemFilter = (typeof FILTER_OPTIONS)[number];

	const jobId = $derived(page.params.id ?? '');

	let job = $state<TeacherJobDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	// Pagination + filter UI state is local; we don't push it into the URL so a refresh
	// always lands you on page 1 of the default view.
	let itemsFilter = $state<ItemFilter>('all');
	let itemsPage = $state(1);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void jobId;
		void itemsFilter;
		void itemsPage;
		void load();
		timer = setInterval(load, REFRESH_MS);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	async function load() {
		if (!jobId) return;
		try {
			job = await api.getTeacherJob(jobId, {
				items_status: itemsFilter === 'all' ? undefined : itemsFilter,
				items_page: itemsPage,
				items_page_size: PAGE_SIZE
			});
			error = null;
		} catch (e: unknown) {
			error =
				e && typeof e === 'object' && 'error' in e
					? String((e as { error: unknown }).error)
					: 'Failed to load job';
		} finally {
			loading = false;
		}
	}

	async function cancelJob() {
		if (!job) return;
		try {
			await api.cancelTeacherJob(job.id);
			await load();
		} catch {
			// ignore
		}
	}

	function setFilter(next: ItemFilter) {
		if (next === itemsFilter) return;
		itemsFilter = next;
		itemsPage = 1; // restart pagination on filter change
	}

	function goToPage(target: number) {
		if (!job) return;
		const clamped = Math.max(1, Math.min(target, job.items_pages));
		if (clamped === itemsPage) return;
		itemsPage = clamped;
	}

	const pct = $derived(job && job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0);

	function statusBadge(status: string): string {
		switch (status) {
			case 'queued':
				return 'bg-info text-white';
			case 'running':
				return 'bg-primary text-white';
			case 'done':
				return 'bg-success text-white';
			case 'error':
				return 'bg-warning-strong text-white';
			case 'skipped':
				return 'bg-border text-text';
			case 'pending':
				return 'bg-info text-white';
			case 'cancelled':
				return 'bg-border text-text';
			default:
				return 'bg-bg text-text';
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('de-DE', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		});
	}

	function filterChips(filter: Record<string, unknown> | null | undefined): [string, string][] {
		if (!filter) return [];
		return Object.entries(filter)
			.filter(([, v]) => v !== null && v !== undefined && v !== '')
			.map(([k, v]) => [k, String(v)] as [string, string]);
	}

	function statusCount(status: string): number {
		return job?.status_counts?.[status] ?? 0;
	}

	function sampleHref(sampleId: string): string {
		// Carry teacher_job context (and the current items filter/page) so the sample
		// detail page can fetch its prev/next neighbours from this job's item list
		// instead of the global samples roster. Arrow-keys then walk through the job.
		const sp = new URLSearchParams();
		sp.set('teacher_job', jobId);
		if (itemsFilter !== 'all') sp.set('teacher_job_items_status', itemsFilter);
		if (itemsPage > 1) sp.set('teacher_job_items_page', String(itemsPage));
		return `/samples/${sampleId}?${sp.toString()}`;
	}

	function sampleThumbUrl(sampleId: string): string {
		return api.sampleImageUrl(sampleId);
	}

	function formatUsd(value: number | null | undefined): string {
		if (value == null) return '—';
		if (value === 0) return '$0.00';
		if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
		return `$${value.toFixed(2)}`;
	}
</script>

<svelte:head>
	<title>Teacher Job - Hive</title>
</svelte:head>

<div class="mb-6 flex items-end justify-between gap-3">
	<div class="min-w-0">
		<div class="mb-1 text-xs text-text-muted">
			<a href="/samples" class="hover:underline">Samples</a>
			<span class="mx-1">/</span>
			<a href="/admin/teacher-jobs" class="hover:underline">Teacher Jobs</a>
			<span class="mx-1">/</span>
			<span class="font-mono">{jobId.slice(0, 8)}</span>
		</div>
		<h1 class="text-2xl font-bold text-text">Teacher Job Detail</h1>
		{#if job}
			<p class="mt-1 text-sm text-text-muted">
				{job.openrouter_model} · created {formatDate(job.created_at)}
				{#if job.finished_at}· finished {formatDate(job.finished_at)}{/if}
			</p>
		{/if}
	</div>
	<div class="flex items-center gap-2">
		{#if job?.status === 'pending' || job?.status === 'running'}
			<Button variant="secondary" size="sm" onclick={cancelJob}>Cancel job</Button>
		{/if}
	</div>
</div>

{#if loading && !job}
	<Spinner />
{:else if error && !job}
	<div class="border border-border bg-surface px-6 py-12 text-center text-sm text-text-muted">
		{error}
	</div>
{:else if job}
	<div class="mb-5 border border-border bg-surface">
		<div class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2.5">
			<span class="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider {statusBadge(job.status)}">
				{job.status}
			</span>
			<span class="tabular-nums text-sm font-medium text-text">{job.processed}/{job.total}</span>
			<span class="text-xs text-text-muted">{pct}%</span>
			<span
				class="tabular-nums text-xs text-text"
				title="Real billed cost from OpenRouter so far"
			>
				{formatUsd(job.cost_usd)}
				{#if job.cost_usd_estimated_total != null && job.status !== 'done' && job.status !== 'cancelled'}
					<span class="text-text-muted">/ est. {formatUsd(job.cost_usd_estimated_total)}</span>
				{/if}
			</span>
			<div class="ml-auto flex flex-wrap gap-3 text-[11px]">
				<span><span class="font-semibold text-info">{statusCount('queued')}</span> <span class="text-text-muted">queued</span></span>
				<span><span class="font-semibold text-primary">{statusCount('running')}</span> <span class="text-text-muted">running</span></span>
				<span><span class="font-semibold text-success">{statusCount('done')}</span> <span class="text-text-muted">done</span></span>
				{#if statusCount('error') > 0}
					<span><span class="font-semibold text-warning-strong">{statusCount('error')}</span> <span class="text-text-muted">error</span></span>
				{/if}
				{#if statusCount('skipped') > 0}
					<span><span class="font-semibold text-text-muted">{statusCount('skipped')}</span> <span class="text-text-muted">skipped</span></span>
				{/if}
			</div>
		</div>
		<div class="h-1.5 bg-bg">
			<div
				class="h-full transition-[width] duration-300 {job.status === 'cancelled' ? 'bg-border' : 'bg-primary'}"
				style="width: {pct}%"
			></div>
		</div>
		<div class="flex flex-wrap items-center gap-2 px-4 py-2 text-[11px]">
			{#each filterChips(job.filter as Record<string, unknown> | null | undefined) as [key, value] (key)}
				<span class="border border-border bg-bg px-1.5 py-0.5 text-text-muted">
					{key}=<span class="text-text">{value}</span>
				</span>
			{:else}
				<span class="text-text-muted">no filter (all samples)</span>
			{/each}
			{#if job.last_error}
				<span class="ml-auto text-warning-strong">last error: {job.last_error}</span>
			{/if}
		</div>
	</div>

	<section>
		<div class="mb-3 flex flex-wrap items-end justify-between gap-3">
			<div>
				<h2 class="text-sm font-semibold uppercase tracking-wider text-text">
					Items
				</h2>
				<p class="text-[11px] text-text-muted">
					{job.items_total.toLocaleString()} match{job.items_total === 1 ? '' : 'es'}
					{itemsFilter !== 'all' ? ` (filtered to ${itemsFilter})` : ''}
				</p>
			</div>
			<div class="flex flex-wrap items-center gap-1 bg-bg p-1">
				{#each FILTER_OPTIONS as opt (opt)}
					{@const opt_count = opt === 'all' ? job.total : statusCount(opt)}
					<button
						type="button"
						onclick={() => setFilter(opt)}
						class="px-2.5 py-1 text-xs font-medium transition-colors {itemsFilter === opt ? 'bg-surface text-text' : 'text-text-muted hover:text-text'}"
					>
						{opt}
						<span class="ml-1 tabular-nums text-text-muted">{opt_count.toLocaleString()}</span>
					</button>
				{/each}
			</div>
		</div>
		{#if job.items.length === 0}
			<div class="border border-border bg-surface px-6 py-8 text-center text-sm text-text-muted">
				{#if itemsFilter === 'all'}
					No items in this job.
				{:else}
					No items with status <span class="font-mono">{itemsFilter}</span>.
				{/if}
			</div>
		{:else}
			{@render itemGrid(job.items)}
		{/if}

		{#if job.items_pages > 1}
			{@const j = job}
			<div class="mt-4 flex items-center justify-between border border-border bg-surface px-4 py-2.5 text-xs">
				<span class="text-text-muted">
					Page {j.items_page} of {j.items_pages} · showing
					{(j.items_page - 1) * j.items_page_size + 1}–{Math.min(j.items_page * j.items_page_size, j.items_total)}
					of {j.items_total.toLocaleString()}
				</span>
				<div class="flex items-center gap-1">
					<button
						type="button"
						onclick={() => goToPage(j.items_page - 1)}
						disabled={j.items_page <= 1}
						class="border border-border px-3 py-1.5 text-xs font-medium text-text hover:bg-bg disabled:opacity-30"
					>
						Previous
					</button>
					{#each Array.from({ length: j.items_pages }, (_, i) => i + 1) as p}
						{#if j.items_pages <= 7 || p === 1 || p === j.items_pages || (p >= j.items_page - 1 && p <= j.items_page + 1)}
							<button
								type="button"
								onclick={() => goToPage(p)}
								class="min-w-[32px] px-2.5 py-1.5 text-xs font-medium {p === j.items_page ? 'bg-primary text-white' : 'text-text hover:bg-bg'}"
							>
								{p}
							</button>
						{:else if p === 2 || p === j.items_pages - 1}
							<span class="px-1 text-text-muted">…</span>
						{/if}
					{/each}
					<button
						type="button"
						onclick={() => goToPage(j.items_page + 1)}
						disabled={j.items_page >= j.items_pages}
						class="border border-border px-3 py-1.5 text-xs font-medium text-text hover:bg-bg disabled:opacity-30"
					>
						Next
					</button>
				</div>
			</div>
		{/if}
	</section>
{/if}

{#snippet itemRow(item: TeacherJobItemSummary)}
	<a
		href={sampleHref(item.sample_id)}
		class="flex items-center gap-3 border border-border bg-surface px-3 py-2 transition-colors hover:border-primary"
	>
		<img
			src={sampleThumbUrl(item.sample_id)}
			alt=""
			loading="lazy"
			class="h-10 w-10 shrink-0 border border-border object-cover"
		/>
		<div class="min-w-0 flex-1">
			<div class="truncate font-mono text-[11px] text-text-muted">{item.sample_id.slice(0, 8)}</div>
			{#if item.error_message}
				<div class="truncate text-[11px] text-warning-strong" title={item.error_message}>{item.error_message}</div>
			{:else if item.detection_count != null}
				<div class="text-[11px] text-text-muted">
					{item.detection_count} piece{item.detection_count === 1 ? '' : 's'}
					{#if item.processed_at}· {formatDate(item.processed_at)}{/if}
				</div>
			{:else if item.processed_at}
				<div class="text-[11px] text-text-muted">{formatDate(item.processed_at)}</div>
			{/if}
		</div>
		<span class="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider {statusBadge(item.status)}">
			{item.status}
		</span>
	</a>
{/snippet}

{#snippet itemGrid(items: TeacherJobItemSummary[])}
	<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
		{#each items as item (item.id)}
			{@render itemRow(item)}
		{/each}
	</div>
{/snippet}
