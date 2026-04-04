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
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#7A7770]"><span class="inline-block h-2.5 w-2.5 bg-[#7A7770]"></span>Total Samples</p>
			<p class="text-2xl font-bold font-mono text-[#1A1A1A]">{stats.total_samples}</p>
		</div>
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#7A7770]"><span class="inline-block h-2.5 w-2.5 bg-[#7A7770]"></span>Unreviewed</p>
			<p class="text-2xl font-bold font-mono text-[#1A1A1A]">{stats.unreviewed_samples}</p>
		</div>
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#0055BF]"><span class="inline-block h-2.5 w-2.5 bg-[#0055BF]"></span>In Review</p>
			<p class="text-2xl font-bold font-mono text-[#0055BF]">{stats.in_review_samples}</p>
		</div>
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#00852B]"><span class="inline-block h-2.5 w-2.5 bg-[#00852B]"></span>Accepted</p>
			<p class="text-2xl font-bold font-mono text-[#00852B]">{stats.accepted_samples}</p>
		</div>
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#D01012]"><span class="inline-block h-2.5 w-2.5 bg-[#D01012]"></span>Rejected</p>
			<p class="text-2xl font-bold font-mono text-[#D01012]">{stats.rejected_samples}</p>
		</div>
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#B8960C]"><span class="inline-block h-2.5 w-2.5 bg-[#FFD500]"></span>Conflict</p>
			<p class="text-2xl font-bold font-mono text-[#B8960C]">{stats.conflict_samples}</p>
		</div>
		<div class="border border-[#E2E0DB] bg-white p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#7A7770]"><span class="inline-block h-2.5 w-2.5 bg-[#7A7770]"></span>Total Machines</p>
			<p class="text-2xl font-bold font-mono text-[#1A1A1A]">{stats.total_machines}</p>
		</div>
	</div>

	<div class="flex gap-4">
		<a
			href="/profiles"
			class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10]"
		>
			Open Profiles
		</a>
		<a
			href="/machines"
			class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
		>
			Manage Machines
		</a>
		<a
			href="/samples"
			class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
		>
			Browse Samples
		</a>
		<a
			href="/review"
			class="border border-[#E2E0DB] px-4 py-2 text-sm font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]"
		>
			Start Reviewing
		</a>
	</div>
{:else}
	<p class="text-gray-500">Failed to load dashboard stats.</p>
{/if}
