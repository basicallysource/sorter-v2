<script lang="ts">
	import { onDestroy } from 'svelte';
	import { api, type SampleDiversityResponse } from '$lib/api';
	import DiversityDonut from '$lib/components/DiversityDonut.svelte';
	import Sparkline from '$lib/components/Sparkline.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	const REFRESH_MS = 5000;

	let data = $state<SampleDiversityResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	async function load() {
		try {
			data = await api.getSampleDiversity();
			error = null;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load diversity stats';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void load();
		timer = setInterval(load, REFRESH_MS);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	function prettifyToken(value: string): string {
		return value
			.split('_')
			.filter(Boolean)
			.map((p) => p.charAt(0).toUpperCase() + p.slice(1))
			.join(' ');
	}

	function formatRelative(iso: string | null): string {
		if (!iso) return '—';
		const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
		if (seconds < 60) return `${Math.round(seconds)}s ago`;
		if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
		if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
		return `${Math.round(seconds / 86400)}d ago`;
	}

	function formatEta(seconds: number | null, lastUploadedAt: string | null, coverage: number): string {
		if (coverage >= 1) return 'done';
		if (lastUploadedAt) {
			const idle = (Date.now() - new Date(lastUploadedAt).getTime()) / 1000;
			if (idle > 600) return 'paused';
		}
		if (seconds === null || seconds <= 0) return 'stalled';
		if (seconds < 60) return 'imminent';
		if (seconds < 3600) return `~${Math.round(seconds / 60)}m`;
		if (seconds < 86400) {
			const h = seconds / 3600;
			return h < 10 ? `~${h.toFixed(1)}h` : `~${Math.round(h)}h`;
		}
		return `~${Math.round(seconds / 86400)}d`;
	}
</script>

<svelte:head>
	<title>Diversity - Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<div>
		<div class="mb-1 text-xs text-text-muted">
			<a href="/samples" class="hover:underline">Samples</a>
			<span class="mx-1">/</span>
			<span>Diversity</span>
		</div>
		<h1 class="text-2xl font-bold text-text">Diversity Overview</h1>
		<p class="mt-1 text-sm text-text-muted">
			Each donut shows how close a capture reason is to full, balanced piece-count diversity. Targets per bucket
			are role-specific — e.g. classification ignores 9+ pieces. Strikethrough wedges are out-of-scope for that
			role and don't drag the score. Refreshes every {REFRESH_MS / 1000}s.
		</p>
	</div>
	{#if data}
		<div class="text-right text-xs text-text-muted">
			<div class="tabular-nums text-text">{data.total.toLocaleString()} samples</div>
			<div>updated {formatRelative(data.generated_at)}</div>
		</div>
	{/if}
</div>

{#if loading && !data}
	<Spinner />
{:else if error && !data}
	<div class="border border-border bg-white px-6 py-12 text-center text-sm text-text-muted">
		{error}
	</div>
{:else if data && data.groups.length === 0}
	<div class="border border-border bg-white px-6 py-12 text-center text-sm text-text-muted">
		No capture reasons recorded yet.
	</div>
{:else if data}
	<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
		{#each data.groups as group (group.capture_reason)}
			<a
				href="/samples/diversity/{encodeURIComponent(group.capture_reason)}"
				class="block border border-border bg-white p-4 transition-colors hover:border-primary"
			>
				<div class="mb-3 flex items-baseline justify-between gap-2">
					<h2 class="truncate text-sm font-semibold text-text">{prettifyToken(group.capture_reason)}</h2>
					<span class="shrink-0 tabular-nums text-xs text-text-muted">
						{group.total.toLocaleString()}
					</span>
				</div>
				<div class="flex justify-center py-2">
					<DiversityDonut
						bucketFills={group.bucket_fills}
						bucketKeys={data.bucket_keys}
						coverage={group.coverage}
						size={220}
					/>
				</div>
				<div class="mt-3">
					<div class="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-text-muted">
						<span>Trend</span>
						<span>ETA <span class="font-semibold text-text">{formatEta(group.eta_seconds, group.last_uploaded_at, group.coverage)}</span></span>
					</div>
					<Sparkline values={group.coverage_trend} height={72} />
				</div>
				<div class="mt-2 flex items-center justify-between text-[11px] text-text-muted">
					<span>
						{group.by_source_role.length} source{group.by_source_role.length === 1 ? '' : 's'}
					</span>
					<span>
						{group.avg_score !== null ? `⌀ ${group.avg_score.toFixed(3)}` : '—'}
					</span>
					<span>{formatRelative(group.last_uploaded_at)}</span>
				</div>
			</a>
		{/each}
	</div>
{/if}
