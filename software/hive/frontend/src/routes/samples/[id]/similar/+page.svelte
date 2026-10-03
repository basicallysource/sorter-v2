<script lang="ts">
	import { page } from '$app/state';
	import { api, type PaginatedSamples, type SampleDetail } from '$lib/api';
	import SampleCard from '$lib/components/SampleCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ImageOff from '@lucide/svelte/icons/image-off';
	import ScanSearch from '@lucide/svelte/icons/scan-search';

	const sampleId = $derived(page.params.id ?? '');

	let target = $state<SampleDetail | null>(null);
	let data = $state<PaginatedSamples | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);
	let maxDistance = $state(12);

	$effect(() => {
		if (!sampleId) return;
		void load();
	});

	async function load() {
		loading = true;
		loadError = null;
		try {
			const [t, similar] = await Promise.all([
				api.getSample(sampleId),
				api.getSimilarSamples(sampleId, { limit: 48, max_distance: maxDistance })
			]);
			target = t;
			data = similar;
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'Could not load similar samples.';
		} finally {
			loading = false;
		}
	}

	async function setDistance(next: number) {
		if (next === maxDistance) return;
		maxDistance = next;
		await load();
	}

	const DISTANCE_OPTIONS = [
		{ value: 4, label: 'Very strict, 4' },
		{ value: 8, label: 'Strict, 8' },
		{ value: 12, label: 'The default, 12' },
		{ value: 16, label: 'Loose, 16' },
		{ value: 24, label: 'Very loose, 24' }
	];

</script>

<svelte:head>
	<title>Similar samples - Hive</title>
</svelte:head>

<div>
	<Button href={`/samples/${sampleId}`} size="sm" variant="ghost" icon={ArrowLeft}>Sample</Button>
</div>

<PageHeader
	title="Similar samples"
	description="Samples that look like this one, by perceptual hash: bursts of near-identical frames, uploads made twice, batches under the same light."
/>

<Panel flush>
	<div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-(--pad-panel) py-3">
		<span class="label">Most distance</span>
		<Select
			class="w-44"
			size="sm"
			label="Most distance"
			value={String(maxDistance)}
			options={DISTANCE_OPTIONS.map((o) => ({ value: String(o.value), label: o.label }))}
			onchange={(v: string) => void setDistance(Number(v))}
		/>
		<span class="min-w-0 flex-[1_1_16rem] text-sm text-ink-muted"
			>The Hamming distance over the 64-bit hash. Lower is closer; 12 or less usually looks like a duplicate.</span
		>
	</div>
</Panel>

{#if loading}
	<div class="flex justify-center p-8"><Spinner size={32} /></div>
{:else if loadError}
	<Alert tone="danger">{loadError}</Alert>
{:else if target === null}
	<Panel><EmptyState icon={ImageOff} title="Sample not found" /></Panel>
{:else}
	<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
		<!-- The sample itself comes first, ringed, so the others read against it. -->
		<div class="rounded-panel outline-2 outline-offset-2 outline-primary" title="This sample">
			<SampleCard sample={target} href={`/samples/${target.id}`} />
		</div>
		{#if data}
			{#each data.items as sample (sample.id)}
				<SampleCard {sample} href={`/samples/${sample.id}/similar`} />
			{/each}
		{/if}
	</div>

	{#if data && data.items.length === 0}
		<Panel>
			<EmptyState icon={ScanSearch} title="Nothing this close">
				No samples within {maxDistance}. Try a looser distance. An older sample may not have its hash yet; the backfill adds them in
				batches.
			</EmptyState>
		</Panel>
	{/if}
{/if}
