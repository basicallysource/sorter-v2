<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type SampleDiversityBucketFills, type SampleDiversityResponse } from '$lib/api';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
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

	let data = $state<SampleDiversityResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	const scope = $derived(page.url.searchParams.get('scope') === 'mine' ? 'mine' : 'all');

	async function load() {
		try {
			data = await api.getSampleDiversity(undefined, { scope });
			error = null;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load diversity stats';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void scope;
		void load();
		timer = setInterval(load, REFRESH_MS);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	function setScope(next: 'mine' | 'all') {
		if (next === scope) return;
		const url = new URL(page.url);
		if (next === 'mine') url.searchParams.set('scope', 'mine');
		else url.searchParams.delete('scope');
		void goto(`${url.pathname}${url.search}`, { replaceState: false, noScroll: true, keepFocus: true });
	}

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	const prettifyToken = sentence;

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
	<title>Diversity - Hive</title>
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
	<Button href="/samples" size="sm" variant="ghost" icon={ArrowLeft}>Samples</Button>
</div>

<PageHeader
	title="Diversity"
	description={`How near each capture reason is to full, balanced piece-count diversity. Each bucket's target depends on the role (classification ignores 9 or more pieces), and struck-through wedges don't count. The score is also scaled by how many machines took part (${data?.machine_target ?? 3} before a reason can reach 100%), so one machine alone never reads as done. It refreshes every ${REFRESH_MS / 1000} seconds.`}
>
	{#snippet actions()}
		{#if data}
			<span class="num text-sm text-ink-muted"
				>{data.total.toLocaleString()} samples, updated {formatRelative(data.generated_at)}</span
			>
		{/if}
		<SegmentedControl
			label="Whose samples"
			size="sm"
			value={scope}
			options={[
				{ value: 'all', label: 'All' },
				{ value: 'mine', label: 'Mine' }
			]}
			onchange={setScope}
		/>
	{/snippet}
</PageHeader>

{#if loading && !data}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if error && !data}
	<Alert tone="danger">{error}</Alert>
{:else if data && data.groups.length === 0}
	<Panel><EmptyState icon={ChartPie} title="No capture reasons yet" /></Panel>
{:else if data}
	<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 xl:grid-cols-3">
		{#each data.groups as group (group.capture_reason)}
			{@render card(
				`/samples/diversity/${encodeURIComponent(group.capture_reason)}`,
				prettifyToken(group.capture_reason),
				group.total,
				group.bucket_fills,
				group.coverage,
				group.coverage_trend,
				formatEta(group.eta_seconds, group.last_uploaded_at, group.coverage),
				`${group.machine_count} of ${group.machine_target} machines`,
				group.machine_factor < 1,
				`Coverage is multiplied by ${group.machine_factor.toFixed(2)}.`,
				group.avg_score,
				group.last_uploaded_at,
				group.by_source_role.length
			)}
		{/each}
	</div>
{/if}
