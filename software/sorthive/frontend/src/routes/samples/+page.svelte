<script lang="ts">
	import { api, type PaginatedSamples, type Machine, type SampleFilterOptions } from '$lib/api';
	import SampleCard from '$lib/components/SampleCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let data = $state<PaginatedSamples | null>(null);
	let machines = $state<Machine[]>([]);
	let filterOptions = $state<SampleFilterOptions>({ source_roles: [], capture_reasons: [] });
	let loading = $state(true);

	// Filters
	let filterMachine = $state<string>('');
	let filterStatus = $state<string>('');
	let filterSourceRole = $state<string>('');
	let filterCaptureReason = $state<string>('');
	let currentPage = $state(1);
	const pageSize = 36;

	const sourceRoleLabels: Record<string, string> = {
		classification_chamber: 'Classification Chamber',
		c_channel_1: 'C-Channel 1',
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		carousel: 'Carousel',
		top: 'Top Camera',
		bottom: 'Bottom Camera'
	};

	$effect(() => {
		void loadFilters();
	});

	$effect(() => {
		// Re-run when filters change
		void filterMachine;
		void filterStatus;
		void filterSourceRole;
		void filterCaptureReason;
		void currentPage;
		loadSamples();
	});

	async function loadFilters() {
		try {
			const [nextMachines, nextOptions] = await Promise.all([
				api.getMachines(),
				api.getSampleFilterOptions()
			]);
			machines = nextMachines;
			filterOptions = nextOptions;
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

	function goToPage(page: number) {
		currentPage = page;
	}

	function updateMachineFilter(value: string) {
		filterMachine = value;
		currentPage = 1;
	}

	function updateStatusFilter(value: string) {
		filterStatus = value;
		currentPage = 1;
	}

	function updateSourceRoleFilter(value: string) {
		filterSourceRole = value;
		currentPage = 1;
	}

	function updateCaptureReasonFilter(value: string) {
		filterCaptureReason = value;
		currentPage = 1;
	}

	function clearFilters() {
		filterMachine = '';
		filterStatus = '';
		filterSourceRole = '';
		filterCaptureReason = '';
		currentPage = 1;
	}
</script>

<svelte:head>
	<title>Samples - SortHive</title>
</svelte:head>

<h1 class="mb-6 text-2xl font-bold text-gray-900">Samples</h1>

<!-- Filters -->
<div class="mb-6 flex flex-wrap items-center gap-3">
	<select
		value={filterMachine}
		onchange={(event) => updateMachineFilter((event.currentTarget as HTMLSelectElement).value)}
		class="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
	>
		<option value="">All Machines</option>
		{#each machines as machine (machine.id)}
			<option value={String(machine.id)}>{machine.name}</option>
		{/each}
	</select>
	<select
		value={filterStatus}
		onchange={(event) => updateStatusFilter((event.currentTarget as HTMLSelectElement).value)}
		class="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
	>
		<option value="">All Statuses</option>
		<option value="unreviewed">Unreviewed</option>
		<option value="in_review">In Review</option>
		<option value="accepted">Accepted</option>
		<option value="rejected">Rejected</option>
		<option value="conflict">Conflict</option>
	</select>
	<select
		value={filterSourceRole}
		onchange={(event) => updateSourceRoleFilter((event.currentTarget as HTMLSelectElement).value)}
		class="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
	>
		<option value="">All Sources</option>
		{#each filterOptions.source_roles as sourceRole (sourceRole)}
			<option value={sourceRole}>{sourceRoleLabel(sourceRole)}</option>
		{/each}
	</select>
	<select
		value={filterCaptureReason}
		onchange={(event) => updateCaptureReasonFilter((event.currentTarget as HTMLSelectElement).value)}
		class="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
	>
		<option value="">All Capture Reasons</option>
		{#each filterOptions.capture_reasons as captureReason (captureReason)}
			<option value={captureReason}>{captureReasonLabel(captureReason)}</option>
		{/each}
	</select>
	{#if filterMachine || filterStatus || filterSourceRole || filterCaptureReason}
		<button
			type="button"
			onclick={clearFilters}
			class="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-50"
		>
			Clear Filters
		</button>
	{/if}
</div>

{#if loading}
	<Spinner />
{:else if !data || data.items.length === 0}
	<p class="text-gray-500">No samples found.</p>
{:else}
	<div class="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
		{#each data.items as sample (sample.id)}
			<SampleCard {sample} href={`/samples/${sample.id}`} />
		{/each}
	</div>

	<!-- Pagination -->
	{#if data.pages > 1}
		<div class="flex items-center justify-center gap-2">
			<button
				onclick={() => goToPage(currentPage - 1)}
				disabled={currentPage <= 1}
				class="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
			>
				Previous
			</button>
			<span class="text-sm text-gray-600">
				Page {data.page} of {data.pages}
			</span>
			<button
				onclick={() => goToPage(currentPage + 1)}
				disabled={currentPage >= data.pages}
				class="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
			>
				Next
			</button>
		</div>
	{/if}
{/if}
