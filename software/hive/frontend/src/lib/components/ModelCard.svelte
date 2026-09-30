<script lang="ts">
	import type { DetectionModelSummary } from '$lib/api';
	import { relativeTime } from '$lib/time';
	import Badge from './Badge.svelte';
	import Card from './Card.svelte';

	interface Props {
		model: DetectionModelSummary;
	}

	let { model }: Props = $props();

	type MetaRecord = Record<string, unknown>;
	function asRecord(v: unknown): MetaRecord | null {
		return v && typeof v === 'object' && !Array.isArray(v) ? (v as MetaRecord) : null;
	}
	function asNumber(v: unknown): number | null {
		return typeof v === 'number' && Number.isFinite(v) ? v : null;
	}
	function asInt(v: unknown): number | null {
		const n = asNumber(v);
		return n === null ? null : Math.round(n);
	}

	const meta = $derived(asRecord(model.training_metadata));
	const modelMeta = $derived(asRecord(meta?.model));
	const datasetMeta = $derived(asRecord(meta?.dataset));
	const best = $derived(asRecord(modelMeta?.best_metrics));

	const map50 = $derived(asNumber(best?.mAP50));
	const map50_95 = $derived(asNumber(best?.mAP50_95));
	const recall = $derived(asNumber(best?.recall));

	const samples = $derived(asInt(datasetMeta?.total) ?? asInt(datasetMeta?.train_samples));
	const machineCount = $derived(asInt(asRecord(datasetMeta?.machines)?.count));

	// Diversity score = normalized Shannon entropy of per-machine sample shares.
	// 0 = single rig (training set is one camera's worth of bias), 1.0 = perfect
	// equal split across all contributing machines. The number above gives an
	// at-a-glance answer to "is this model overfit to one rig?".
	const diversityScore = $derived.by<number | null>(() => {
		const dist = asRecord(asRecord(datasetMeta?.machines)?.distribution_after_balance);
		if (!dist) return null;
		const counts: number[] = [];
		for (const value of Object.values(dist)) {
			const txt = typeof value === 'string' ? value : String(value);
			const match = txt.match(/(\d[\d.,]*)/);
			if (match) counts.push(parseInt(match[1].replace(/[.,]/g, ''), 10));
		}
		if (counts.length < 2) return counts.length === 1 ? 0 : null;
		const total = counts.reduce((a, b) => a + b, 0);
		if (total === 0) return null;
		const shares = counts.map((c) => c / total);
		const entropy = -shares.reduce((acc, p) => acc + (p > 0 ? p * Math.log(p) : 0), 0);
		const maxEntropy = Math.log(counts.length);
		return maxEntropy > 0 ? entropy / maxEntropy : 0;
	});

	const arch = $derived(typeof modelMeta?.architecture === 'string' ? (modelMeta.architecture as string) : null);
	const imgsz = $derived(asInt(modelMeta?.imgsz));

	function formatPct(v: number | null): string {
		return v === null ? '-' : v.toFixed(3);
	}
</script>

{#snippet cell(label: string, value: string, title?: string)}
	<div class="min-w-0 px-3 py-2" {title}>
		<div class="truncate text-sm text-ink-muted">{label}</div>
		<div class="num truncate text-sm font-medium text-ink">{value}</div>
	</div>
{/snippet}

<Card href="/models/{model.id}" label={model.codename ?? model.name} padded={false} class="overflow-hidden">
	<div class="flex items-center gap-3 px-(--pad-panel) py-3">
		{#if model.codename_color}
			<span class="size-11 shrink-0 rounded-control" style="background-color: {model.codename_color}" aria-hidden="true"></span>
		{/if}
		<div class="min-w-0 flex-1">
			<h3 class="truncate text-base font-semibold text-ink">{model.codename ?? model.name}</h3>
			<p class="truncate text-sm text-ink-muted">
				<span class="font-mono">{model.slug}</span>, v{model.version}, {relativeTime(model.published_at)}
			</p>
		</div>
		<div class="flex shrink-0 flex-col items-end gap-1 self-start">
			<Badge tone={model.experimental ? 'warning' : 'success'}>{model.experimental ? 'Experimental' : 'Stable'}</Badge>
			{#if !model.is_public}<Badge>Private</Badge>{/if}
		</div>
	</div>

	{#if map50 !== null || map50_95 !== null}
		<div class="grid grid-cols-3 divide-x divide-line border-t border-line">
			{@render cell('mAP50', formatPct(map50))}
			{@render cell('mAP50-95', formatPct(map50_95))}
			{@render cell('Recall', formatPct(recall))}
		</div>
	{/if}
	{#if arch || imgsz || samples !== null || machineCount !== null}
		<div class="grid grid-cols-3 divide-x divide-line border-t border-line">
			{@render cell('Model', arch && imgsz ? `${arch} @ ${imgsz}` : (arch ?? (imgsz ? `${imgsz} x ${imgsz}` : '-')))}
			{@render cell('Samples', samples !== null ? samples.toLocaleString() : '-')}
			{@render cell(
				'Diversity',
				diversityScore !== null ? diversityScore.toFixed(3) : '-',
				'How evenly the samples come from different machines: 0 is one machine, 1 an even split.'
			)}
		</div>
	{:else if model.description}
		<p class="line-clamp-2 border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">{model.description}</p>
	{/if}
</Card>
