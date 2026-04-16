<script lang="ts">
	import { api, type StatsOverview } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let stats = $state<StatsOverview | null>(null);
	let loading = $state(true);

	$effect(() => {
		loadStats();
	});

	async function loadStats() {
		loading = true;
		try {
			stats = await api.getOverview();
		} catch {
			stats = null;
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Dashboard - Hive</title>
</svelte:head>

<div class="mb-6">
	<h1 class="text-2xl font-bold text-text">Dashboard</h1>
	<p class="mt-1 text-sm text-text-muted">Welcome back{auth.user?.display_name ? `, ${auth.user.display_name}` : ''}.</p>
</div>

{#if loading}
	<Spinner />
{:else if stats}
	<div class="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-text-muted"><span class="inline-block h-2.5 w-2.5 bg-text-muted"></span>Total Samples</p>
			<p class="text-2xl font-bold font-mono text-text">{stats.total_samples}</p>
		</div>
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-text-muted"><span class="inline-block h-2.5 w-2.5 bg-text-muted"></span>Unreviewed</p>
			<p class="text-2xl font-bold font-mono text-text">{stats.unreviewed_samples}</p>
		</div>
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-info"><span class="inline-block h-2.5 w-2.5 bg-info"></span>In Review</p>
			<p class="text-2xl font-bold font-mono text-info">{stats.in_review_samples}</p>
		</div>
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-success"><span class="inline-block h-2.5 w-2.5 bg-success"></span>Accepted</p>
			<p class="text-2xl font-bold font-mono text-success">{stats.accepted_samples}</p>
		</div>
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-primary"><span class="inline-block h-2.5 w-2.5 bg-primary"></span>Rejected</p>
			<p class="text-2xl font-bold font-mono text-primary">{stats.rejected_samples}</p>
		</div>
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#B8960C]"><span class="inline-block h-2.5 w-2.5 bg-warning"></span>Conflict</p>
			<p class="text-2xl font-bold font-mono text-[#B8960C]">{stats.conflict_samples}</p>
		</div>
		<div class="border border-border bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-text-muted"><span class="inline-block h-2.5 w-2.5 bg-text-muted"></span>Total Machines</p>
			<p class="text-2xl font-bold font-mono text-text">{stats.total_machines}</p>
		</div>
	</div>

	<div class="flex gap-4">
		<a
			href="/profiles"
			class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
		>
			Open Profiles
		</a>
		<a
			href="/machines"
			class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
		>
			Manage Machines
		</a>
		<a
			href="/samples"
			class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
		>
			Browse Samples
		</a>
		<a
			href="/review"
			class="border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
		>
			Start Reviewing
		</a>
	</div>
{:else}
	<p class="text-text-muted">Failed to load dashboard stats.</p>
{/if}
