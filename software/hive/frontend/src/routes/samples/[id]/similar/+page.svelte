<script lang="ts">
	import { page } from '$app/state';
	import { api, type PaginatedSamples, type SampleDetail } from '$lib/api';
	import SampleCard from '$lib/components/SampleCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

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
		{ value: 4, label: 'Very strict (≤4)' },
		{ value: 8, label: 'Strict (≤8)' },
		{ value: 12, label: 'Default (≤12)' },
		{ value: 16, label: 'Loose (≤16)' },
		{ value: 24, label: 'Very loose (≤24)' }
	];

</script>

<svelte:head>
	<title>Similar samples · Hive</title>
</svelte:head>

<div class="space-y-4">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<h1 class="text-2xl font-bold text-text">Find Similar</h1>
			<p class="mt-1 text-sm text-text-muted">
				Visually-similar samples by perceptual hash (8×8 DCT). Good for spotting bursts of near-identical frames, redundant uploads, or batches shot under the same conditions.
			</p>
		</div>
		<a
			href={`/samples/${sampleId}`}
			class="inline-flex items-center gap-1 border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text hover:bg-bg"
		>
			← Back to sample
		</a>
	</div>

	<div class="flex flex-wrap items-center gap-2 border border-border bg-surface px-3 py-2">
		<span class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Max distance</span>
		<div class="inline-flex border border-border">
			{#each DISTANCE_OPTIONS as opt}
				<button
					type="button"
					class="border-l border-border px-2.5 py-1 text-xs first:border-l-0 {maxDistance === opt.value ? 'bg-primary text-white' : 'text-text hover:bg-bg'}"
					onclick={() => void setDistance(opt.value)}
				>
					{opt.label}
				</button>
			{/each}
		</div>
		<span class="text-[11px] text-text-muted">Hamming distance over the 64-bit pHash. Lower = more similar; ≤12 is the typical "looks like a duplicate" threshold.</span>
	</div>

	{#if loading}
		<Spinner />
	{:else if loadError}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">{loadError}</div>
	{:else if target === null}
		<div class="border border-border bg-surface px-3 py-2 text-sm text-text-muted">Target sample not found.</div>
	{:else}
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
			<!-- Pin the target as the first card so the comparison is anchored visually. -->
			<div class="relative">
				<SampleCard sample={target} href={`/samples/${target.id}`} />
				<div class="pointer-events-none absolute -top-1 -right-1 border border-primary bg-primary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-white">
					Target
				</div>
			</div>
			{#if data}
				{#each data.items as sample (sample.id)}
					<SampleCard {sample} href={`/samples/${sample.id}/similar`} />
				{/each}
			{/if}
		</div>

		{#if data && data.items.length === 0}
			<div class="border border-border bg-surface px-3 py-6 text-center text-sm text-text-muted">
				No samples within distance ≤{maxDistance}. Try a looser threshold above. If the target sample is older it may not have a pHash yet — the backfill script populates them in batches.
			</div>
		{/if}
	{/if}
</div>
