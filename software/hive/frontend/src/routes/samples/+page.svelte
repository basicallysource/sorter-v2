<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type PaginatedSamples, type Machine, type SampleFilterOptions, type StatsOverview } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
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
	const filterMachine = $derived(listContext.machine_id ?? '');
	const filterStatus = $derived(listContext.review_status ?? '');
	const filterSourceRole = $derived(listContext.source_role ?? '');
	const filterCaptureReason = $derived(listContext.capture_reason ?? '');
	const currentPage = $derived(listContext.page);
	const pageSize = $derived(listContext.page_size);

	const filterContextQuery = $derived(sampleListContextQuery(page.url.searchParams));

	const sourceRoleLabels: Record<string, string> = {
		classification_chamber: 'Classification Chamber',
		c_channel_1: 'C-Channel 1',
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
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

	const hasActiveFilters = $derived(filterMachine || filterStatus || filterSourceRole || filterCaptureReason);

	$effect(() => {
		void loadFilters();
	});

	$effect(() => {
		void filterMachine;
		void filterStatus;
		void filterSourceRole;
		void filterCaptureReason;
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
			const [nextMachines, nextOptions, nextStats] = await Promise.all([
				api.getMachines(),
				api.getSampleFilterOptions(),
				api.getOverview()
			]);
			machines = nextMachines;
			filterOptions = nextOptions;
			stats = nextStats;
		} catch {
			// ignore
		}
	}

	async function loadSamples() {
		loading = true;
		try {
			data = await api.getSamples({
				page: currentPage,
				page_size: pageSize,
				machine_id: filterMachine || undefined,
				review_status: filterStatus || undefined,
				source_role: filterSourceRole || undefined,
				capture_reason: filterCaptureReason || undefined
			});
		} catch {
			data = null;
		} finally {
			loading = false;
		}
	}

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

	function captureReasonLabel(value: string): string {
		return prettifyToken(value);
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

	function updateMachineFilter(value: string) {
		setFilterValue('machine_id', value);
	}

	function updateSourceRoleFilter(value: string) {
		setFilterValue('source_role', value);
	}

	function updateCaptureReasonFilter(value: string) {
		setFilterValue('capture_reason', value);
	}

	function clearFilters() {
		pushFilterUrl((sp) => {
			sp.delete('machine_id');
			sp.delete('review_status');
			sp.delete('source_role');
			sp.delete('capture_reason');
			sp.delete('page');
		});
	}
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
	{#if auth.isReviewer}
		<a
			href="/review"
			class="inline-flex items-center gap-2 bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
		>
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
			</svg>
			Review Samples
		</a>
	{/if}
</div>

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

			<!-- Machine -->
			{#if machines.length > 0}
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
						{#each machines as machine (machine.id)}
							<li>
								<button
									onclick={() => updateMachineFilter(String(machine.id))}
									class="w-full truncate px-2 py-1 text-left text-xs {filterMachine === String(machine.id) ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
								>
									{machine.name}
								</button>
							</li>
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
								class="w-full px-2 py-1 text-left text-xs {filterSourceRole === '' ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								All
							</button>
						</li>
						{#each filterOptions.source_roles as sourceRole (sourceRole)}
							<li>
								<button
									onclick={() => updateSourceRoleFilter(sourceRole)}
									class="w-full px-2 py-1 text-left text-xs {filterSourceRole === sourceRole ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
								>
									{sourceRoleLabel(sourceRole)}
								</button>
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			<!-- Capture Reason -->
			{#if filterOptions.capture_reasons.length > 0}
				<div>
					<h3 class="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">Capture Reason</h3>
					<ul class="space-y-0.5">
						<li>
							<button
								onclick={() => updateCaptureReasonFilter('')}
								class="w-full px-2 py-1 text-left text-xs {filterCaptureReason === '' ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
							>
								All
							</button>
						</li>
						{#each filterOptions.capture_reasons as captureReason (captureReason)}
							<li>
								<button
									onclick={() => updateCaptureReasonFilter(captureReason)}
									class="w-full px-2 py-1 text-left text-xs {filterCaptureReason === captureReason ? 'bg-primary-light font-medium text-primary' : 'text-text hover:bg-bg'}"
								>
									{captureReasonLabel(captureReason)}
								</button>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
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
