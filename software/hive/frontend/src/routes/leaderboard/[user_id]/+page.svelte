<script lang="ts">
	import { page } from '$app/state';
	import { api, type ReviewerProfile } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	const userId = $derived(page.params.user_id ?? '');

	let profile = $state<ReviewerProfile | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		if (!userId) return;
		void load();
	});

	async function load() {
		loading = true;
		error = null;
		try {
			profile = await api.getReviewerProfile(userId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load profile.';
		} finally {
			loading = false;
		}
	}

	function initials(name: string | null): string {
		if (!name) return '?';
		return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || '?';
	}

	function pct(n: number | null): string {
		return n === null ? '—' : `${Math.round(n * 100)}%`;
	}

	function spark(values: number[]): string {
		// SVG path for a minimal sparkline. 14 days wide × 30 high.
		if (values.length === 0) return '';
		const w = 14 * (values.length - 1 || 1);
		const max = Math.max(1, ...values);
		const points = values.map((v, i) => {
			const x = i * 14;
			const y = 30 - (v / max) * 28;
			return `${i === 0 ? 'M' : 'L'}${x.toFixed(0)},${y.toFixed(1)}`;
		});
		return points.join(' ') + ` L${w},30 L0,30 Z`;
	}

	function sparkLine(values: number[]): string {
		if (values.length === 0) return '';
		const max = Math.max(1, ...values);
		return values.map((v, i) => `${i === 0 ? 'M' : 'L'}${i * 14},${(30 - (v / max) * 28).toFixed(1)}`).join(' ');
	}
</script>

<svelte:head>
	<title>{profile?.display_name ?? 'Reviewer'} · Leaderboard · Hive</title>
</svelte:head>

<div class="space-y-5">
	<div>
		<a href="/leaderboard" class="text-xs text-primary hover:underline">← Back to leaderboard</a>
	</div>

	{#if loading}
		<Spinner />
	{:else if error}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>
	{:else if profile}
		{@const isMe = auth.user?.id === profile.user_id}
		<!-- Header card -->
		<div class="border border-border bg-surface">
			<div class="flex flex-wrap items-center gap-4 p-5">
				{#if profile.avatar_url}
					<img src={profile.avatar_url} alt="" class="h-20 w-20 shrink-0 rounded-full border border-border bg-bg object-cover" />
				{:else}
					<span class="flex h-20 w-20 shrink-0 items-center justify-center rounded-full border border-border bg-bg text-2xl font-semibold text-text-muted">
						{initials(profile.display_name)}
					</span>
				{/if}
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-baseline gap-2">
						<h1 class="text-2xl font-bold text-text">{profile.display_name ?? 'Anonymous'}</h1>
						<span class="text-[11px] uppercase tracking-wider text-text-muted">{profile.role}</span>
						{#if isMe}<span class="border border-primary/30 bg-primary-light px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-primary">You</span>{/if}
					</div>
					{#if profile.first_review_at}
						<p class="mt-1 text-xs text-text-muted">
							Reviewing since {new Date(profile.first_review_at).toLocaleDateString()}
						</p>
					{/if}
				</div>
			</div>

			<!-- Contributions breakdown: samples vs pieces (kept separate) -->
			<div class="grid grid-cols-2 gap-px border-t border-border bg-border sm:grid-cols-3">
				<div class="bg-surface px-4 py-3">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Total contributions</div>
					<div class="text-2xl font-bold text-text">{profile.total_contributions.toLocaleString()}</div>
					<div class="text-[11px] text-text-muted">reviews + piece labels</div>
				</div>
				<div class="bg-surface px-4 py-3">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Sample reviews</div>
					<div class="text-2xl font-bold text-text">{profile.total_reviews.toLocaleString()}</div>
					<div class="text-[11px] text-text-muted">
						<span class="text-success">{profile.accepts}</span> ✓ ·
						<span class="text-primary">{profile.rejects}</span> ✗
					</div>
				</div>
				<div class="bg-surface px-4 py-3">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Piece labels</div>
					<div class="text-2xl font-bold text-text">{(profile.piece_color_labels + profile.piece_crop_links).toLocaleString()}</div>
					<div class="text-[11px] text-text-muted">{profile.piece_color_labels} color · {profile.piece_crop_links} same-piece</div>
				</div>
			</div>

			<!-- Review quality metrics -->
			<div class="grid grid-cols-2 gap-px border-t border-border bg-border sm:grid-cols-3">
				<div class="bg-surface px-4 py-3">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Agreement</div>
					<div class="text-2xl font-bold text-text">{pct(profile.agreement_rate)}</div>
					<div class="text-[11px] text-text-muted">vs final consensus</div>
				</div>
				<div class="bg-surface px-4 py-3">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Current streak</div>
					<div class="text-2xl font-bold text-text">{profile.current_streak_days}d</div>
					<div class="text-[11px] text-text-muted">longest: {profile.longest_streak_days}d</div>
				</div>
				<div class="bg-surface px-4 py-3">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Best day</div>
					<div class="text-2xl font-bold text-text">{profile.speed_record_24h}</div>
					<div class="text-[11px] text-text-muted">{profile.machines_covered} machine{profile.machines_covered === 1 ? '' : 's'} covered</div>
				</div>
			</div>

			<!-- Sparkline -->
			{#if profile.daily_counts.length > 0}
				<div class="border-t border-border px-4 py-3">
					<div class="mb-2 flex items-baseline justify-between">
						<span class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Last 14 days</span>
						<span class="text-[11px] text-text-muted">
							{profile.daily_counts.reduce((s, v) => s + v, 0)} reviews
						</span>
					</div>
					<svg viewBox="0 0 {14 * (profile.daily_counts.length - 1 || 1)} 30" class="block h-10 w-full" preserveAspectRatio="none">
						<path d={spark(profile.daily_counts)} fill="rgba(208,16,18,0.10)" />
						<path d={sparkLine(profile.daily_counts)} fill="none" stroke="#D01012" stroke-width="1.5" />
					</svg>
				</div>
			{/if}
		</div>

		<!-- Achievements -->
		<div class="border border-border bg-surface">
			<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-2">
				<h2 class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Achievements</h2>
				<span class="text-[11px] text-text-muted">
					{profile.achievements.filter((a) => a.earned).length} / {profile.achievements.length} earned
				</span>
			</div>
			<div class="grid grid-cols-1 gap-px bg-border sm:grid-cols-2 lg:grid-cols-3">
				{#each profile.achievements as a (a.slug)}
					<div class="flex items-start gap-3 bg-surface p-3 {a.earned ? '' : 'opacity-50'}">
						<div class="text-2xl leading-none">{a.icon}</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="text-sm font-semibold text-text">{a.name}</span>
								<span class="border px-1 py-0.5 text-[9px] uppercase tracking-wider {
									a.tier === 'gold' ? 'border-warning/30 bg-warning/10 text-[#A16207]'
									: a.tier === 'silver' ? 'border-border bg-bg text-text-muted'
									: 'border-border bg-bg text-text-muted'
								}">{a.tier}</span>
							</div>
							<p class="mt-0.5 text-xs leading-snug text-text-muted">{a.description}</p>
							<p class="mt-1 text-[11px] {a.earned ? 'text-success' : 'text-text-muted'}">
								{a.earned ? '✓ ' : ''}{a.progress}
							</p>
						</div>
					</div>
				{/each}
			</div>
		</div>
	{:else}
		<div class="border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted">
			Reviewer not found.
		</div>
	{/if}
</div>
