<script lang="ts">
	import { api, type LeaderboardResponse, type StatsOverview } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Spinner from '$lib/components/Spinner.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import Button from '$lib/components/Button.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Alert from '$lib/components/Alert.svelte';

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

<PageHeader
	title="Dashboard"
	description="Welcome back{auth.user?.display_name ? `, ${auth.user.display_name}` : ''}."
>
	{#snippet actions()}
		<Button href="/machines">Manage machines</Button>
		<Button href="/samples">Browse samples</Button>
		<Button href="/review">Start reviewing</Button>
		<Button href="/profiles" variant="primary">Open profiles</Button>
	{/snippet}
</PageHeader>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if stats}
	<div class="flex flex-col gap-(--gap-panels)">
		<!-- Each cell draws its own top and left line; the grid is pulled 1px up and left
		     so the lines on the outer edges are clipped. The lines fall between cells only,
		     and a last row that is not full leaves the panel's fill, not a dark gap. -->
		<section aria-label="Samples" class="overflow-hidden rounded-panel bg-surface">
			<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7">
				{#each [
					{ label: 'Total samples', value: stats.total_samples },
					{ label: 'Unreviewed', value: stats.unreviewed_samples },
					{ label: 'In review', value: stats.in_review_samples },
					{ label: 'Accepted', value: stats.accepted_samples, tone: 'success' as const },
					{ label: 'Rejected', value: stats.rejected_samples, tone: 'danger' as const },
					{ label: 'Conflict', value: stats.conflict_samples, tone: 'warning' as const },
					{ label: 'Machines', value: stats.total_machines }
				] as stat (stat.label)}
					<div class="border-t border-l border-line">
						<Stat label={stat.label} value={stat.value.toLocaleString()} tone={stat.tone} />
					</div>
				{/each}
			</div>
		</section>

		<!-- Top reviewers: keeps the gamification right on the landing page, so it
		     is hard to ignore once you have started reviewing. -->
		{#if leaderboard && leaderboard.entries.length > 0}
			<Panel title="Top reviewers" description="The last 7 days." flush>
				{#snippet actions()}
					<Button href="/leaderboard" size="sm" variant="ghost" icon={ArrowRight}>Leaderboard</Button>
				{/snippet}
				<ol class="divide-y divide-line">
					{#each leaderboard.entries as entry, idx (entry.user_id)}
						{@const isMe = auth.user?.id === entry.user_id}
						<li>
							<a
								href={`/leaderboard/${entry.user_id}`}
								class="flex items-center gap-3 px-(--pad-panel) py-2.5 text-sm transition-colors hover:bg-hover"
							>
								<span class="num w-6 text-center text-base text-ink">{MEDALS[idx] ?? idx + 1}</span>
								{#if entry.avatar_url}
									<img src={entry.avatar_url} alt="" class="size-7 shrink-0 rounded-full bg-well object-cover" />
								{:else}
									<span
										class="flex size-7 shrink-0 items-center justify-center rounded-full bg-well text-xs font-medium text-ink-muted"
									>
										{initials(entry.display_name)}
									</span>
								{/if}
								<span class="flex min-w-0 flex-1 items-center gap-2">
									<span class="truncate font-medium text-ink">{entry.display_name ?? 'Anonymous'}</span>
									{#if isMe}<Badge tone="primary">You</Badge>{/if}
								</span>
								<span class="num text-base font-medium text-ink">{entry.total_reviews.toLocaleString()}</span>
								<span class="num w-16 text-right text-sm text-ink-muted">
									<span class="text-success-ink">{entry.accepts}</span>, <span class="text-danger-ink"
										>{entry.rejects}</span
									>
								</span>
							</a>
						</li>
					{/each}
				</ol>
			</Panel>
		{/if}
	</div>
{:else}
	<Alert tone="danger" title="The dashboard did not load">Reload the page to try again.</Alert>
{/if}
