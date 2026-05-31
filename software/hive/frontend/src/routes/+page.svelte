<script lang="ts">
	import { api, type LeaderboardResponse, type StatsOverview } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let stats = $state<StatsOverview | null>(null);
	let loading = $state(true);
	let leaderboard = $state<LeaderboardResponse | null>(null);

	$effect(() => {
		loadStats();
		void loadLeaderboard();
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

	async function loadLeaderboard() {
		try {
			leaderboard = await api.getLeaderboard('7d', 5);
		} catch {
			leaderboard = null;
		}
	}

	const MEDALS = ['🥇', '🥈', '🥉'];

	function initials(name: string | null): string {
		if (!name) return '?';
		return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || '?';
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
		<div class="border border-border bg-surface p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-text-muted"><span class="inline-block h-2.5 w-2.5 bg-text-muted"></span>Total Samples</p>
			<p class="text-2xl font-bold font-mono text-text">{stats.total_samples}</p>
		</div>
		<div class="border border-border bg-surface p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-text-muted"><span class="inline-block h-2.5 w-2.5 bg-text-muted"></span>Unreviewed</p>
			<p class="text-2xl font-bold font-mono text-text">{stats.unreviewed_samples}</p>
		</div>
		<div class="border border-border bg-surface p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-info"><span class="inline-block h-2.5 w-2.5 bg-info"></span>In Review</p>
			<p class="text-2xl font-bold font-mono text-info">{stats.in_review_samples}</p>
		</div>
		<div class="border border-border bg-surface p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-success"><span class="inline-block h-2.5 w-2.5 bg-success"></span>Accepted</p>
			<p class="text-2xl font-bold font-mono text-success">{stats.accepted_samples}</p>
		</div>
		<div class="border border-border bg-surface p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-primary"><span class="inline-block h-2.5 w-2.5 bg-primary"></span>Rejected</p>
			<p class="text-2xl font-bold font-mono text-primary">{stats.rejected_samples}</p>
		</div>
		<div class="border border-border bg-surface p-4">
			<p class="flex items-center gap-2 text-sm font-medium text-[#B8960C]"><span class="inline-block h-2.5 w-2.5 bg-warning"></span>Conflict</p>
			<p class="text-2xl font-bold font-mono text-[#B8960C]">{stats.conflict_samples}</p>
		</div>
		<div class="border border-border bg-surface p-4">
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

	<!-- Top reviewers widget — keeps the gamification visible right on the
	     landing page so it's hard to ignore once you've started reviewing. -->
	{#if leaderboard && leaderboard.entries.length > 0}
		<div class="mt-8 border border-border bg-surface">
			<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-2">
				<h2 class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Top reviewers · last 7 days</h2>
				<a href="/leaderboard" class="text-xs text-primary hover:underline">View full leaderboard →</a>
			</div>
			<div>
				{#each leaderboard.entries as entry, idx (entry.user_id)}
					{@const isMe = auth.user?.id === entry.user_id}
					{@const medal = idx < 3 ? MEDALS[idx] : null}
					<a
						href={`/leaderboard/${entry.user_id}`}
						class="flex items-center gap-3 border-b border-border px-4 py-2.5 text-sm transition-colors hover:bg-bg {isMe ? 'bg-primary-light/30' : ''} last:border-b-0"
					>
						<span class="w-6 text-center text-base font-semibold tabular-nums text-text">
							{medal ?? idx + 1}
						</span>
						{#if entry.avatar_url}
							<img src={entry.avatar_url} alt="" class="h-7 w-7 shrink-0 rounded-full border border-border bg-bg object-cover" />
						{:else}
							<span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-bg text-[10px] font-semibold text-text-muted">
								{initials(entry.display_name)}
							</span>
						{/if}
						<span class="min-w-0 flex-1 truncate font-medium text-text">
							{entry.display_name ?? 'Anonymous'}
							{#if isMe}<span class="ml-1 text-[10px] uppercase tracking-wider text-primary">you</span>{/if}
						</span>
						<span class="text-base font-bold tabular-nums text-text">{entry.total_reviews.toLocaleString()}</span>
						<span class="text-[11px] tabular-nums text-text-muted">
							<span class="text-success">{entry.accepts}</span>·<span class="text-primary">{entry.rejects}</span>
						</span>
					</a>
				{/each}
			</div>
		</div>
	{/if}
{:else}
	<p class="text-text-muted">Failed to load dashboard stats.</p>
{/if}
