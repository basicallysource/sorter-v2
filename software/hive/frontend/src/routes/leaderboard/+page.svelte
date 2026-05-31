<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api, type LeaderboardEntry, type LeaderboardResponse } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	type Period = '24h' | '7d' | '30d' | 'all';

	const PERIOD_OPTIONS: { value: Period; label: string }[] = [
		{ value: '24h', label: 'Last 24h' },
		{ value: '7d', label: 'Last 7 days' },
		{ value: '30d', label: 'Last 30 days' },
		{ value: 'all', label: 'All time' }
	];

	const initialPeriod = $derived(((page.url.searchParams.get('period') as Period | null) ?? '7d') as Period);

	let period = $state<Period>(initialPeriod);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let data = $state<LeaderboardResponse | null>(null);

	$effect(() => {
		void load(period);
	});

	async function load(p: Period) {
		loading = true;
		error = null;
		try {
			data = await api.getLeaderboard(p);
		} catch (e) {
			// Show whatever we can about the failure so a "Failed to fetch"
			// doesn't look like a magic black box. Browser fetch() throws a
			// TypeError on network/CORS/connection failure; backend errors
			// throw a structured ApiError object.
			console.error('Leaderboard fetch failed:', e);
			if (e instanceof TypeError) {
				error = `Network/CORS error: ${e.message} (check DevTools Network tab — request likely never reached the backend)`;
			} else if (e instanceof Error) {
				error = e.message;
			} else if (e && typeof e === 'object' && 'error' in e) {
				error = String((e as { error: unknown }).error ?? 'Unknown server error');
			} else {
				error = 'Failed to load leaderboard.';
			}
		} finally {
			loading = false;
		}
	}

	function setPeriod(p: Period) {
		if (p === period) return;
		period = p;
		const url = new URL(page.url);
		if (p === '7d') url.searchParams.delete('period');
		else url.searchParams.set('period', p);
		void goto(`${url.pathname}${url.search}`, { replaceState: true, noScroll: true, keepFocus: true });
	}

	const medals = ['🥇', '🥈', '🥉'];

	function medalFor(idx: number): string | null {
		return idx < 3 ? medals[idx] : null;
	}

	function relativeTime(iso: string | null): string {
		if (!iso) return '—';
		const ms = Date.now() - new Date(iso).getTime();
		const m = Math.floor(ms / 60000);
		if (m < 1) return 'just now';
		if (m < 60) return `${m}m ago`;
		const h = Math.floor(m / 60);
		if (h < 24) return `${h}h ago`;
		const d = Math.floor(h / 24);
		if (d < 30) return `${d}d ago`;
		return new Date(iso).toLocaleDateString();
	}

	function initials(name: string | null): string {
		if (!name) return '?';
		return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || '?';
	}

	function profileHref(entry: LeaderboardEntry): string {
		return `/leaderboard/${entry.user_id}`;
	}
</script>

<svelte:head>
	<title>Leaderboard · Hive</title>
</svelte:head>

<div class="space-y-5">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<h1 class="text-2xl font-bold text-text">Reviewer leaderboard</h1>
			<p class="mt-1 text-sm text-text-muted">
				Who's keeping the queue flowing. Period switches the ranking; clicks open a reviewer's full stats + achievements.
			</p>
		</div>
		<div class="flex border border-border bg-surface text-xs">
			{#each PERIOD_OPTIONS as opt}
				<button
					type="button"
					class="border-l border-border px-3 py-1.5 first:border-l-0 {period === opt.value ? 'bg-primary text-white' : 'text-text hover:bg-bg'}"
					onclick={() => setPeriod(opt.value)}
				>
					{opt.label}
				</button>
			{/each}
		</div>
	</div>

	{#if loading}
		<Spinner />
	{:else if error}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>
	{:else if !data || data.entries.length === 0}
		<div class="border border-border bg-surface px-3 py-10 text-center text-sm text-text-muted">
			No reviews in this period yet. Be the first.
		</div>
	{:else}
		<div class="border border-border bg-surface">
			<div class="grid grid-cols-[40px_1fr_120px_150px_140px] items-center gap-3 border-b border-border bg-bg px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
				<span>Rank</span>
				<span>Reviewer</span>
				<span class="text-right">Reviews</span>
				<span class="text-right">✓ Accept · ✗ Reject</span>
				<span class="text-right">Last activity</span>
			</div>
			{#each data.entries as entry, idx (entry.user_id)}
				{@const isMe = auth.user?.id === entry.user_id}
				{@const medal = medalFor(idx)}
				<a
					href={profileHref(entry)}
					class="grid grid-cols-[40px_1fr_120px_150px_140px] items-center gap-3 border-b border-border px-4 py-2.5 text-sm transition-colors hover:bg-bg {isMe ? 'bg-primary-light/30' : ''} last:border-b-0"
				>
					<span class="text-center text-base font-semibold tabular-nums text-text">
						{medal ?? idx + 1}
					</span>
					<span class="flex min-w-0 items-center gap-2">
						{#if entry.avatar_url}
							<img src={entry.avatar_url} alt="" class="h-7 w-7 rounded-full border border-border bg-bg object-cover" />
						{:else}
							<span class="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-bg text-[10px] font-semibold text-text-muted">
								{initials(entry.display_name)}
							</span>
						{/if}
						<span class="min-w-0">
							<span class="block truncate font-medium text-text">
								{entry.display_name ?? 'Anonymous'}
								{#if isMe}<span class="ml-1 text-[10px] uppercase tracking-wider text-primary">you</span>{/if}
							</span>
							<span class="block truncate text-[11px] text-text-muted">{entry.role}</span>
						</span>
					</span>
					<span class="text-right text-base font-bold tabular-nums text-text">
						{entry.total_reviews.toLocaleString()}
					</span>
					<span class="text-right text-xs tabular-nums text-text-muted">
						<span class="text-success">{entry.accepts}</span> · <span class="text-primary">{entry.rejects}</span>
					</span>
					<span class="text-right text-xs text-text-muted">{relativeTime(entry.last_review_at)}</span>
				</a>
			{/each}
		</div>
	{/if}
</div>
