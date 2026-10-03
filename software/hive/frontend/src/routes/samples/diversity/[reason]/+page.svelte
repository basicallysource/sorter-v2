<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/state';
	import {
		api,
		type SampleDiversityBucketFills,
		type SampleDiversityGroup,
		type SampleDiversityResponse
	} from '$lib/api';
	import DiversityDonut from '$lib/components/DiversityDonut.svelte';
	import Sparkline from '$lib/components/Sparkline.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { sentence } from '$lib/text';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ChartPie from '@lucide/svelte/icons/chart-pie';

	const REFRESH_MS = 5000;

	const captureReason = $derived(page.params.reason ?? '');
	const scope = $derived(page.url.searchParams.get('scope') === 'mine' ? 'mine' : 'all');

	let data = $state<SampleDiversityResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	const group = $derived<SampleDiversityGroup | null>(data?.groups[0] ?? null);

	async function load() {
		if (!captureReason) return;
		try {
			data = await api.getSampleDiversity(captureReason, { scope });
			error = null;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load diversity detail';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void captureReason;
		void scope;
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
		classification_channel: 'Classification channel',
		classification_chamber: 'Classification chamber',
		c_channel_1: 'C-channel 1',
		c_channel_2: 'C-channel 2',
		c_channel_3: 'C-channel 3',
		carousel: 'Carousel',
		piece_crop: 'Piece crop',
		top: 'Top camera',
		bottom: 'Bottom camera'
	};

	const prettifyToken = sentence;

	function sourceLabel(value: string): string {
		return sourceRoleLabels[value] ?? prettifyToken(value);
	}

	function samplesHref(sourceRole: string): string {
		const sp = new URLSearchParams();
		sp.set('capture_reason', captureReason);
		if (sourceRole && sourceRole !== 'unknown') sp.set('source_role', sourceRole);
		if (scope === 'mine') sp.set('scope', 'mine');
		return `/samples?${sp.toString()}`;
	}

	function formatRelative(iso: string | null): string {
		if (!iso) return '-';
		const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
		if (seconds < 60) return `${Math.round(seconds)} s ago`;
		if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
		if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
		return `${Math.round(seconds / 86400)} d ago`;
	}

	function formatEta(seconds: number | null, lastUploadedAt: string | null, coverage: number): string {
		if (coverage >= 1) return 'Full';
		if (lastUploadedAt) {
			const idle = (Date.now() - new Date(lastUploadedAt).getTime()) / 1000;
			if (idle > 600) return 'Paused';
		}
		if (seconds === null || seconds <= 0) return 'Stalled';
		if (seconds < 60) return 'Full any moment';
		if (seconds < 3600) return `Full in about ${Math.round(seconds / 60)} min`;
		if (seconds < 86400) {
			const h = seconds / 3600;
			return `Full in about ${h < 10 ? h.toFixed(1) : Math.round(h)} h`;
		}
		return `Full in about ${Math.round(seconds / 86400)} d`;
	}
</script>

<svelte:head>
	<title>{prettifyToken(captureReason)} - Diversity - Hive</title>
</svelte:head>

{#snippet card(href: string, title: string, total: number, fills: SampleDiversityBucketFills, coverage: number, trend: number[], eta: string, machines: string, machinesShort: boolean, machinesTitle: string, score: number | null, last: string | null, sources?: number)}
	<Card {href} label={title}>
		<div class="mb-3 flex items-baseline justify-between gap-2">
			<h2 class="truncate font-semibold text-ink">{title}</h2>
			<span class="num shrink-0 text-sm text-ink-muted">{total.toLocaleString()}</span>
		</div>
		<div class="flex justify-center py-2">
			<DiversityDonut bucketFills={fills} bucketKeys={data!.bucket_keys} {coverage} size={220} />
		</div>
		<div class="mt-3">
			<div class="mb-1 flex items-center justify-between text-sm text-ink-muted">
				<span>Trend</span>
				<span class="font-medium text-ink">{eta}</span>
			</div>
			<Sparkline values={trend} height={72} />
		</div>
		<div class="num mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-sm text-ink-muted">
			{#if sources != null}<span>{sources} source{sources === 1 ? '' : 's'}</span>{/if}
			<span class={machinesShort ? 'text-warning-ink' : ''} title={machinesTitle}>{machines}</span>
			<span title="The average score">{score !== null ? `Score ${score.toFixed(3)}` : 'No scores'}</span>
			<span>{formatRelative(last)}</span>
		</div>
	</Card>
{/snippet}

<div>
	<Button href="/samples/diversity" size="sm" variant="ghost" icon={ArrowLeft}>Diversity</Button>
</div>

<PageHeader
	title={prettifyToken(captureReason)}
	description={`A donut for each channel: each wedge is a piece-count bucket, filling toward its role's target, and struck-through wedges don't count. The balanced donut is the mean of the sources, so a bucket is full only when every channel that matters has it. It refreshes every ${REFRESH_MS / 1000} seconds.`}
>
	{#snippet actions()}
		{#if data && group}
			<span class="num text-sm text-ink-muted"
				>{group.total.toLocaleString()} samples, updated {formatRelative(data.generated_at)}</span
			>
		{/if}
	{/snippet}
</PageHeader>

{#if loading && !data}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if error && !data}
	<Alert tone="danger">{error}</Alert>
{:else if !group || !data}
	<Panel><EmptyState icon={ChartPie} title="No samples for this capture reason" /></Panel>
{:else}
	<Panel>
		<div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
			<div class="flex flex-wrap items-center gap-4">
				<DiversityDonut bucketFills={group.bucket_fills} bucketKeys={data.bucket_keys} coverage={group.coverage} size={180} />
				<div class="num flex flex-col gap-1 text-sm text-ink-muted">
					<div class="label">Balanced, the mean of the sources</div>
					<div class="text-2xl font-semibold text-ink">{group.total.toLocaleString()}</div>
					<div>{group.avg_score !== null ? `Average score ${group.avg_score.toFixed(3)}` : 'No scores'}</div>
					<div class={group.machine_factor < 1 ? 'text-warning-ink' : ''} title={`Coverage is multiplied by ${group.machine_factor.toFixed(2)}.`}>
						{group.machine_count} of {group.machine_target} machines
					</div>
					<div>Last {formatRelative(group.last_uploaded_at)}</div>
				</div>
			</div>
			<div class="num text-sm text-ink-muted md:text-right">
				<div class="label">The default target a bucket</div>
				<div class="text-2xl font-semibold text-ink">{data.default_target_per_bucket}</div>
				<div>Over {data.bucket_keys.length} piece-count buckets</div>
			</div>
		</div>
		<div class="mt-4">
			<div class="mb-1 flex items-center justify-between text-sm text-ink-muted">
				<span>Trend</span>
				<span class="font-medium text-ink">{formatEta(group.eta_seconds, group.last_uploaded_at, group.coverage)}</span>
			</div>
			<Sparkline values={group.coverage_trend} height={100} />
		</div>
	</Panel>

	<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 xl:grid-cols-3">
		{#each group.by_source_role as role (role.source_role)}
			{@render card(
				samplesHref(role.source_role),
				sourceLabel(role.source_role),
				role.total,
				role.bucket_fills,
				role.coverage,
				role.coverage_trend,
				formatEta(role.eta_seconds, role.last_uploaded_at, role.coverage),
				`${role.machine_count} of ${role.machine_target} machines`,
				role.machine_factor < 1,
				`Coverage is multiplied by ${role.machine_factor.toFixed(2)}.`,
				role.avg_score,
				role.last_uploaded_at
			)}
		{/each}
	</div>
{/if}
