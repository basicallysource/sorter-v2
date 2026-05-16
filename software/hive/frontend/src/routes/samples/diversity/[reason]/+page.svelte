<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { api, type SampleDiversityGroup, type SampleDiversityResponse } from '$lib/api';
	import DiversityDonut from '$lib/components/DiversityDonut.svelte';
	import Sparkline from '$lib/components/Sparkline.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	const REFRESH_MS = 5000;

	const captureReason = $derived(page.params.reason ?? '');

	let data = $state<SampleDiversityResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	const group = $derived<SampleDiversityGroup | null>(data?.groups[0] ?? null);

	async function load() {
		if (!captureReason) return;
		try {
			data = await api.getSampleDiversity(captureReason);
			error = null;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load diversity detail';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void captureReason;
		void load();
		timer = setInterval(load, REFRESH_MS);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	const sourceRoleLabels: Record<string, string> = {
		classification_channel: 'Classification Channel',
		classification_chamber: 'Classification Chamber',
		c_channel_1: 'C-Channel 1',
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		carousel: 'Carousel',
		piece_crop: 'Piece Crop',
		top: 'Top Camera',
		bottom: 'Bottom Camera'
	};

	function prettifyToken(value: string): string {
		return value
			.split('_')
			.filter(Boolean)
			.map((p) => p.charAt(0).toUpperCase() + p.slice(1))
			.join(' ');
	}

	function sourceLabel(value: string): string {
		return sourceRoleLabels[value] ?? prettifyToken(value);
	}

	function samplesHref(sourceRole: string): string {
		const sp = new URLSearchParams();
		sp.set('capture_reason', captureReason);
		if (sourceRole && sourceRole !== 'unknown') sp.set('source_role', sourceRole);
		return `/samples?${sp.toString()}`;
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
	<title>{prettifyToken(captureReason)} - Diversity - Hive</title>
</svelte:head>

<div class="mb-6 flex items-center justify-between">
	<div>
		<div class="mb-1 text-xs text-text-muted">
			<a href="/samples" class="hover:underline">Samples</a>
			<span class="mx-1">/</span>
			<a href="/samples/diversity" class="hover:underline">Diversity</a>
			<span class="mx-1">/</span>
			<span>{prettifyToken(captureReason)}</span>
		</div>
		<h1 class="text-2xl font-bold text-text">{prettifyToken(captureReason)}</h1>
		<p class="mt-1 text-sm text-text-muted">
			One donut per channel — each wedge is a piece-count bucket and fills toward its role-specific target.
			Struck-through wedges are excluded from the score. The "Balanced" donut at the top is the mean of all
			sources, so a bucket only counts as full when every relevant channel has it. Refreshes every {REFRESH_MS / 1000}s.
		</p>
	</div>
	{#if data && group}
		<div class="text-right text-xs text-text-muted">
			<div class="tabular-nums text-text">{group.total.toLocaleString()} samples</div>
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
{:else if !group || !data}
	<div class="border border-border bg-white px-6 py-12 text-center text-sm text-text-muted">
		No samples found for this capture reason.
	</div>
{:else}
	<section class="mb-4 border border-border bg-white p-4">
		<div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
			<div class="flex items-center gap-4">
				<DiversityDonut
					bucketFills={group.bucket_fills}
					bucketKeys={data.bucket_keys}
					coverage={group.coverage}
					size={180}
				/>
				<div class="space-y-1">
					<div class="text-xs uppercase tracking-wider text-text-muted">Balanced (mean of sources)</div>
					<div class="tabular-nums text-2xl font-bold text-text">{group.total.toLocaleString()}</div>
					<div class="text-xs text-text-muted">
						{group.avg_score !== null ? `⌀ score ${group.avg_score.toFixed(3)}` : 'no scores'}
					</div>
					<div class="text-xs text-text-muted">last {formatRelative(group.last_uploaded_at)}</div>
				</div>
			</div>
			<div class="text-right text-xs text-text-muted">
				<div>Default target / bucket</div>
				<div class="tabular-nums text-2xl font-bold text-text">{data.default_target_per_bucket}</div>
				<div>across {data.bucket_keys.length} piece-count buckets</div>
			</div>
		</div>
		<div class="mt-4">
			<div class="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-text-muted">
				<span>Trend</span>
				<span>ETA to 100% <span class="font-semibold text-text">{formatEta(group.eta_seconds, group.last_uploaded_at, group.coverage)}</span></span>
			</div>
			<Sparkline values={group.coverage_trend} height={100} />
		</div>
	</section>

	<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
		{#each group.by_source_role as role (role.source_role)}
			<a
				href={samplesHref(role.source_role)}
				class="block border border-border bg-white p-4 transition-colors hover:border-primary"
			>
				<div class="mb-3 flex items-baseline justify-between gap-2">
					<h2 class="truncate text-sm font-semibold text-text">{sourceLabel(role.source_role)}</h2>
					<span class="shrink-0 tabular-nums text-xs text-text-muted">{role.total.toLocaleString()}</span>
				</div>
				<div class="flex justify-center py-2">
					<DiversityDonut
						bucketFills={role.bucket_fills}
						bucketKeys={data.bucket_keys}
						coverage={role.coverage}
						size={220}
					/>
				</div>
				<div class="mt-3">
					<div class="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-text-muted">
						<span>Trend</span>
						<span>ETA <span class="font-semibold text-text">{formatEta(role.eta_seconds, role.last_uploaded_at, role.coverage)}</span></span>
					</div>
					<Sparkline values={role.coverage_trend} height={72} />
				</div>
				<div class="mt-2 flex items-center justify-between text-[11px] text-text-muted">
					<span>{role.avg_score !== null ? `⌀ ${role.avg_score.toFixed(3)}` : '—'}</span>
					<span>{formatRelative(role.last_uploaded_at)}</span>
				</div>
			</a>
		{/each}
	</div>
{/if}
