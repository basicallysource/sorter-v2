<script lang="ts">
	import { page } from '$app/state';
	import { api, type ReviewerProfile } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { sentence } from '$lib/text';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Check from '@lucide/svelte/icons/check';

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
		return n === null ? '-' : `${Math.round(n * 100)}%`;
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
	<title>{profile?.display_name ?? 'Reviewer'} - Leaderboard - Hive</title>
</svelte:head>

<div>
	<Button href="/leaderboard" size="sm" variant="ghost" icon={ArrowLeft}>Leaderboard</Button>
</div>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if error}
	<Alert tone="danger">{error}</Alert>
{:else if profile}
	{@const isMe = auth.user?.id === profile.user_id}
	<div class="flex flex-col gap-(--gap-panels)">
		<div class="flex items-start gap-4">
			{#if profile.avatar_url}
				<img src={profile.avatar_url} alt="" class="size-14 shrink-0 rounded-full bg-well object-cover" />
			{:else}
				<span class="flex size-14 shrink-0 items-center justify-center rounded-full bg-surface text-xl font-medium text-ink-muted"
					>{initials(profile.display_name)}</span
				>
			{/if}
			<div class="min-w-0 flex-1">
				<PageHeader
					title={profile.display_name ?? 'Anonymous'}
					description={profile.first_review_at
						? `Reviewing since ${new Date(profile.first_review_at).toLocaleDateString()}.`
						: undefined}
				>
					<div class="flex flex-wrap items-center gap-2">
						<Badge>{sentence(profile.role)}</Badge>
						{#if isMe}<Badge tone="primary">You</Badge>{/if}
					</div>
				</PageHeader>
			</div>
		</div>

		<Panel flush>
			<div class="-mt-px -ml-px grid grid-cols-1 sm:grid-cols-3">
				<div class="border-t border-l border-line">
					<Stat label="Contributions" value={profile.total_contributions.toLocaleString()} hint="Reviews and piece labels" />
				</div>
				<div class="border-t border-l border-line">
					<Stat
						label="Sample reviews"
						value={profile.total_reviews.toLocaleString()}
						hint={`${profile.accepts} accepted, ${profile.rejects} rejected`}
					/>
				</div>
				<div class="border-t border-l border-line">
					<Stat
						label="Piece labels"
						value={(profile.piece_color_labels + profile.piece_crop_links).toLocaleString()}
						hint={`${profile.piece_color_labels} color, ${profile.piece_crop_links} same piece`}
					/>
				</div>
				<div class="border-t border-l border-line">
					<Stat label="Agreement" value={pct(profile.agreement_rate)} hint="With the final consensus" />
				</div>
				<div class="border-t border-l border-line">
					<Stat
						label="Current streak"
						value={`${profile.current_streak_days}`}
						unit="days"
						hint={`Longest: ${profile.longest_streak_days} days`}
					/>
				</div>
				<div class="border-t border-l border-line">
					<Stat
						label="Best day"
						value={profile.speed_record_24h}
						hint={`${profile.machines_covered} machine${profile.machines_covered === 1 ? '' : 's'} covered`}
					/>
				</div>
			</div>
			{#if profile.daily_counts.length > 0}
				<div class="border-t border-line px-(--pad-panel) py-3">
					<div class="mb-2 flex items-baseline justify-between text-sm">
						<span class="text-ink-muted">The last 14 days</span>
						<span class="num text-ink-muted">{profile.daily_counts.reduce((s, v) => s + v, 0)} reviews</span>
					</div>
					<svg
						viewBox="0 0 {14 * (profile.daily_counts.length - 1 || 1)} 30"
						class="block h-10 w-full"
						preserveAspectRatio="none"
						role="img"
						aria-label="Reviews a day over the last 14 days"
					>
						<path d={spark(profile.daily_counts)} fill="var(--primary-soft)" />
						<path
							d={sparkLine(profile.daily_counts)}
							fill="none"
							stroke="var(--primary)"
							stroke-width="1.5"
							vector-effect="non-scaling-stroke"
						/>
					</svg>
				</div>
			{/if}
		</Panel>

		<Panel title="Achievements" flush>
			{#snippet actions()}
				<span class="num text-sm text-ink-muted"
					>{profile!.achievements.filter((a) => a.earned).length} of {profile!.achievements.length} earned</span
				>
			{/snippet}
			<div class="-ml-px grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
				{#each profile.achievements as a (a.slug)}
					<div class="flex items-start gap-3 border-t border-l border-line p-4 {a.earned ? '' : 'opacity-50'}">
						<span class="text-2xl leading-none">{a.icon}</span>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="text-sm font-medium text-ink">{a.name}</span>
								<Badge tone={a.tier === 'gold' ? 'warning' : 'neutral'}>{sentence(a.tier)}</Badge>
							</div>
							<p class="mt-0.5 text-sm text-ink-muted">{a.description}</p>
							<p class="mt-1 flex items-center gap-1 text-sm {a.earned ? 'text-success-ink' : 'text-ink-muted'}">
								{#if a.earned}<Check size={14} class="shrink-0" />{/if}{a.progress}
							</p>
						</div>
					</div>
				{/each}
			</div>
		</Panel>
	</div>
{:else}
	<Panel><EmptyState title="Reviewer not found" /></Panel>
{/if}
