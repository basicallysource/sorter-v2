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
	<title>Dashboard - SortHive</title>
</svelte:head>

<div class="mb-6">
	<h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>
	<p class="mt-1 text-sm text-gray-500">Welcome back{auth.user?.display_name ? `, ${auth.user.display_name}` : ''}.</p>
</div>

{#if loading}
	<Spinner />
{:else if stats}
	<div class="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-gray-300 bg-white p-4">
			<p class="text-sm text-gray-500">Total Samples</p>
			<p class="text-2xl font-bold text-gray-900">{stats.total_samples}</p>
		</div>
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-gray-300 bg-white p-4">
			<p class="text-sm text-gray-500">Unreviewed</p>
			<p class="text-2xl font-bold text-gray-900">{stats.unreviewed_samples}</p>
		</div>
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-blue-500 bg-white p-4">
			<p class="text-sm text-gray-500">In Review</p>
			<p class="text-2xl font-bold text-blue-600">{stats.in_review_samples}</p>
		</div>
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-green-500 bg-white p-4">
			<p class="text-sm text-gray-500">Accepted</p>
			<p class="text-2xl font-bold text-green-600">{stats.accepted_samples}</p>
		</div>
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-red-500 bg-white p-4">
			<p class="text-sm text-gray-500">Rejected</p>
			<p class="text-2xl font-bold text-red-600">{stats.rejected_samples}</p>
		</div>
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-yellow-500 bg-white p-4">
			<p class="text-sm text-gray-500">Conflict</p>
			<p class="text-2xl font-bold text-yellow-600">{stats.conflict_samples}</p>
		</div>
		<div class="rounded-lg border border-gray-200 border-l-4 border-l-gray-300 bg-white p-4">
			<p class="text-sm text-gray-500">Total Machines</p>
			<p class="text-2xl font-bold text-gray-900">{stats.total_machines}</p>
		</div>
	</div>

	<div class="flex gap-4">
		<a
			href="/machines"
			class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
		>
			Manage Machines
		</a>
		<a
			href="/samples"
			class="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
		>
			Browse Samples
		</a>
		<a
			href="/review"
			class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
		>
			Start Reviewing
		</a>
	</div>
{:else}
	<p class="text-gray-500">Failed to load dashboard stats.</p>
{/if}
