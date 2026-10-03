<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '$lib/auth.svelte';
	import { api, type TeacherJobDetail, type TeacherJobItemSummary } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Button from '$lib/components/Button.svelte';

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

	function statusTone(status: string): 'primary' | 'info' | 'success' | 'warning' | 'neutral' {
		switch (status) {
			case 'running':
				return 'primary';
			case 'pending':
			case 'queued':
				return 'info';
			case 'done':
				return 'success';
			case 'error':
				return 'warning';
			default:
				return 'neutral';
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('en-US', {
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
		if (value == null) return '-';
		if (value === 0) return '$0.00';
		if (Math.abs(value) < 0.01) return `$${value.toFixed(4)}`;
		return `$${value.toFixed(2)}`;
	}
</script>

<svelte:head>
	<title>Teacher job - Hive</title>
</svelte:head>

<div>
	<Button href="/admin/teacher-jobs" size="sm" variant="ghost" icon={ArrowLeft}>Teacher jobs</Button>
</div>

<PageHeader
	title={`Teacher job ${jobId.slice(0, 8)}`}
	description={job
		? `${job.openrouter_model}. Started ${formatDate(job.created_at)}${job.finished_at ? `, finished ${formatDate(job.finished_at)}` : ''}.`
		: undefined}
>
	{#snippet actions()}
		{#if job?.status === 'pending' || job?.status === 'running'}
			<Button onclick={cancelJob}>Cancel job</Button>
		{/if}
	{/snippet}
</PageHeader>

{#if loading && !job}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if error && !job}
	<Alert tone="danger">{error}</Alert>
{:else if job}
	<!-- The pages of the samples, a footer only when there is more than one. -->
	{#snippet pager()}
		{@const j = job!}
		<span class="num mr-auto text-sm text-ink-muted"
			>Page {j.items_page} of {j.items_pages}: {(j.items_page - 1) * j.items_page_size + 1} to {Math.min(
				j.items_page * j.items_page_size,
				j.items_total
			)} of {j.items_total.toLocaleString()}</span
		>
		<Button size="sm" disabled={j.items_page <= 1} onclick={() => goToPage(j.items_page - 1)}>Previous</Button>
		{#each Array.from({ length: j.items_pages }, (_, i) => i + 1) as p (p)}
			{#if j.items_pages <= 7 || p === 1 || p === j.items_pages || (p >= j.items_page - 1 && p <= j.items_page + 1)}
				<Button size="sm" variant={p === j.items_page ? 'primary' : 'ghost'} onclick={() => goToPage(p)}>{p}</Button>
			{:else if p === 2 || p === j.items_pages - 1}
				<span class="text-sm text-ink-muted">...</span>
			{/if}
		{/each}
		<Button size="sm" disabled={j.items_page >= j.items_pages} onclick={() => goToPage(j.items_page + 1)}>Next</Button>
	{/snippet}
	<div class="flex flex-col gap-(--gap-panels)">
		<Panel flush>
			<div class="flex flex-wrap items-center gap-3 px-(--pad-panel) py-3 text-sm">
				<Badge tone={statusTone(job.status)} dot>{sentence(job.status)}</Badge>
				<span class="num font-medium text-ink">{job.processed} of {job.total}</span>
				<span class="num text-ink-muted">{pct}%</span>
				<span class="num text-ink" title="What OpenRouter has billed so far"
					>{formatUsd(job.cost_usd)}{#if job.cost_usd_estimated_total != null && job.status !== 'done' && job.status !== 'cancelled'}<span
							class="text-ink-muted">, about {formatUsd(job.cost_usd_estimated_total)} in all</span
						>{/if}</span
				>
				<div class="num ml-auto flex flex-wrap gap-3 text-ink-muted">
					<span><span class="text-info-ink">{statusCount('queued')}</span> queued</span>
					<span><span class="text-primary-ink">{statusCount('running')}</span> running</span>
					<span><span class="text-success-ink">{statusCount('done')}</span> done</span>
					{#if statusCount('error') > 0}<span><span class="text-warning-ink">{statusCount('error')}</span> failed</span>{/if}
					{#if statusCount('skipped') > 0}<span><span class="text-ink">{statusCount('skipped')}</span> skipped</span>{/if}
				</div>
			</div>
			<div class="px-(--pad-panel) pb-3">
				<ProgressBar label="Job progress" value={pct} />
			</div>
			<div class="flex flex-wrap items-center gap-2 border-t border-line px-(--pad-panel) py-3 text-sm">
				{#each filterChips(job.filter as Record<string, unknown> | null | undefined) as [key, value] (key)}
					<Badge>{key} <span class="text-ink">{value}</span></Badge>
				{:else}
					<span class="text-ink-muted">Every sample, no filter</span>
				{/each}
			</div>
			{#if job.last_error}
				<div class="px-(--pad-panel) pb-3"><Alert tone="warning" title="Last error">{job.last_error}</Alert></div>
			{/if}
		</Panel>

		<Panel
			title="Samples"
			description={`${job.items_total.toLocaleString()} match${job.items_total === 1 ? '' : 'es'}${itemsFilter !== 'all' ? `, ${itemsFilter} only` : ''}.`}
			footer={job.items_pages > 1 ? pager : undefined}
		>
			{#snippet actions()}
				<SegmentedControl
					label="Show"
					size="sm"
					value={itemsFilter}
					onchange={setFilter}
					options={FILTER_OPTIONS.map((opt) => ({
						value: opt,
						label: `${sentence(opt)} ${(opt === 'all' ? job!.total : statusCount(opt)).toLocaleString()}`
					}))}
				/>
			{/snippet}
			{#if job.items.length === 0}
				<EmptyState title={itemsFilter === 'all' ? 'No samples in this job' : `No ${itemsFilter} samples`} />
			{:else}
				<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
					{#each job.items as item (item.id)}
						<a
							href={sampleHref(item.sample_id)}
							class="flex items-center gap-3 rounded-control bg-well px-3 py-2 transition-colors hover:bg-hover"
						>
							<img src={sampleThumbUrl(item.sample_id)} alt="" loading="lazy" class="size-10 shrink-0 rounded-control bg-media object-cover" />
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm text-ink-muted">{item.sample_id.slice(0, 8)}</span>
								{#if item.error_message}
									<span class="block truncate text-sm text-warning-ink" title={item.error_message}>{item.error_message}</span>
								{:else if item.detection_count != null}
									<span class="num block text-sm text-ink-muted"
										>{item.detection_count} piece{item.detection_count === 1 ? '' : 's'}{#if item.processed_at}, {formatDate(
												item.processed_at
											)}{/if}</span
									>
								{:else if item.processed_at}
									<span class="block text-sm text-ink-muted">{formatDate(item.processed_at)}</span>
								{/if}
							</span>
							<Badge tone={statusTone(item.status)}>{sentence(item.status)}</Badge>
						</a>
					{/each}
				</div>
			{/if}
		</Panel>
	</div>
{/if}
