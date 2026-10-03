<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { api, type LeaderboardEntry, type LeaderboardResponse } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { sentence } from '$lib/text';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Trophy from '@lucide/svelte/icons/trophy';

	type Period = '24h' | '7d' | '30d' | 'all';

	const PERIOD_OPTIONS: { value: Period; label: string }[] = [
		{ value: '24h', label: '24 hours' },
		{ value: '7d', label: '7 days' },
		{ value: '30d', label: '30 days' },
		{ value: 'all', label: 'All time' }
	];

	// Read once, when the page opens: the period in the link, else a week.
	const initialPeriod = (page.url.searchParams.get('period') as Period | null) ?? '7d';

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
				error = `Network or CORS error: ${e.message}. The request probably never reached the server; the browser's network tab shows why.`;
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
		if (!iso) return '-';
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
	<title>Leaderboard - Hive</title>
</svelte:head>

<PageHeader
	title="Contributor leaderboard"
	description="Ranked by contributions: sample reviews plus piece labels (color and same piece). Open a person for their numbers and achievements."
>
	{#snippet actions()}
		<SegmentedControl
			label="Period"
			size="sm"
			value={period}
			onchange={setPeriod}
			options={PERIOD_OPTIONS}
		/>
	{/snippet}
</PageHeader>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if error}
	<Alert tone="danger">{error}</Alert>
{:else if !data || data.entries.length === 0}
	<Panel>
		<EmptyState icon={Trophy} title="No contributions yet">Nobody has contributed in this period. Be the first.</EmptyState>
	</Panel>
{:else}
	<Panel flush>
		<!-- A phone keeps rank, name and total on one line and puts the two detail
		     columns on a second; the five columns need about 480px. -->
		<div
			class="grid grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 bg-well px-(--pad-panel) py-2 text-sm font-medium text-ink-muted sm:grid-cols-[2.5rem_1fr_6rem_10rem_8rem]"
		>
			<span>Rank</span>
			<span>Contributor</span>
			<span class="text-right">Total</span>
			<span class="hidden text-right sm:block">Samples, pieces</span>
			<span class="hidden text-right sm:block">Last active</span>
		</div>
		<ol class="divide-y divide-line">
			{#each data.entries as entry, idx (entry.user_id)}
				{@const isMe = auth.user?.id === entry.user_id}
				<li>
					<a
						href={profileHref(entry)}
						class="grid grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-(--pad-panel) py-2.5 text-sm transition-colors hover:bg-hover sm:grid-cols-[2.5rem_1fr_6rem_10rem_8rem] {isMe
							? 'bg-primary-soft'
							: ''}"
					>
						<span class="num text-center text-base text-ink">{medalFor(idx) ?? idx + 1}</span>
						<span class="flex min-w-0 items-center gap-2">
							{#if entry.avatar_url}
								<img src={entry.avatar_url} alt="" class="size-7 shrink-0 rounded-full bg-well object-cover" />
							{:else}
								<span
									class="flex size-7 shrink-0 items-center justify-center rounded-full bg-well text-xs font-medium text-ink-muted"
									>{initials(entry.display_name)}</span
								>
							{/if}
							<span class="min-w-0">
								<span class="flex items-center gap-2">
									<span class="truncate font-medium text-ink">{entry.display_name ?? 'Anonymous'}</span>
									{#if isMe}<Badge tone="primary">You</Badge>{/if}
								</span>
								<span class="block truncate text-ink-muted">{sentence(entry.role)}</span>
							</span>
						</span>
						<span class="num text-right text-base font-medium text-ink">{entry.total_contributions.toLocaleString()}</span>
						<span class="num col-start-2 row-start-2 text-ink-muted sm:col-start-auto sm:row-start-auto sm:text-right">
							<span title="Sample reviews">{entry.total_reviews.toLocaleString()}</span>,
							<span title="Piece color labels and same-piece links"
								>{(entry.piece_color_labels + entry.piece_crop_links).toLocaleString()}</span
							>
						</span>
						<span class="col-start-3 row-start-2 text-right text-ink-muted sm:col-start-auto sm:row-start-auto"
							>{relativeTime(entry.last_review_at)}</span
						>
					</a>
				</li>
			{/each}
		</ol>
	</Panel>
{/if}
