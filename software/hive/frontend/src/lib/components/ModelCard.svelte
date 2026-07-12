<script lang="ts">
	import type { DetectionModelSummary } from '$lib/api';
	import Badge from './Badge.svelte';

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

	function relativeTime(iso: string): string {
		const then = new Date(iso).getTime();
		if (!Number.isFinite(then)) return '';
		const diffMs = Date.now() - then;
		const sec = Math.round(diffMs / 1000);
		if (sec < 60) return 'gerade eben';
		const min = Math.round(sec / 60);
		if (min < 60) return `vor ${min} min`;
		const hr = Math.round(min / 60);
		if (hr < 24) return `vor ${hr} Std`;
		const days = Math.round(hr / 24);
		if (days < 7) return `vor ${days} Tag${days === 1 ? '' : 'en'}`;
		const weeks = Math.round(days / 7);
		if (weeks < 5) return `vor ${weeks} Woche${weeks === 1 ? '' : 'n'}`;
		return new Date(iso).toLocaleDateString('de-DE', { year: 'numeric', month: 'short', day: 'numeric' });
	}

	function formatPct(v: number | null): string {
		return v === null ? '—' : v.toFixed(3);
	}
</script>

<a
	href="/models/{model.id}"
	class="block border border-[var(--color-border)] bg-[var(--color-surface)] transition-colors hover:border-primary"
>
	<!-- Header — codename swatch sized to the codename+subtitle stack height -->
	<div class="flex items-stretch gap-3 border-b border-[var(--color-border)] px-4 py-3">
		{#if model.codename_color}
			<div class="flex shrink-0 items-center">
				<span
					class="block aspect-square w-12 rounded-full border border-[var(--color-border)]"
					style="background-color: {model.codename_color}"
					aria-hidden="true"
				></span>
			</div>
		{/if}
		<div class="min-w-0 flex-1 self-center">
			{#if model.codename}
				<h3 class="truncate text-xl font-bold leading-tight text-[var(--color-text)]">{model.codename}</h3>
			{:else}
				<h3 class="truncate text-base font-semibold text-[var(--color-text)]">{model.name}</h3>
			{/if}
			<p class="truncate font-mono text-[11px] text-[var(--color-text-muted)]">
				{model.slug} · v{model.version} · {relativeTime(model.published_at)}
			</p>
		</div>
		<div class="flex shrink-0 flex-col items-end gap-1 self-start">
			{#if model.experimental}
				<Badge text="Experimental" variant="warning" />
			{:else}
				<Badge text="Stable" variant="success" />
			{/if}
			{#if !model.is_public}
				<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Private</span>
			{/if}
		</div>
	</div>

	<!-- Metric pills — three columns: mAP50, mAP50_95, Recall -->
	{#if map50 !== null || map50_95 !== null}
		<div class="grid grid-cols-3 gap-px border-b border-[var(--color-border)] bg-[var(--color-border)]">
			<div class="bg-[var(--color-surface)] px-3 py-2">
				<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">mAP50</div>
				<div class="font-mono text-sm font-semibold text-[var(--color-text)]">{formatPct(map50)}</div>
			</div>
			<div class="bg-[var(--color-surface)] px-3 py-2">
				<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">mAP50_95</div>
				<div class="font-mono text-sm font-semibold text-[var(--color-text)]">{formatPct(map50_95)}</div>
			</div>
			<div class="bg-[var(--color-surface)] px-3 py-2">
				<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Recall</div>
				<div class="font-mono text-sm font-semibold text-[var(--color-text)]">{formatPct(recall)}</div>
			</div>
		</div>
	{/if}

	<!-- Body — 3 columns matching the metric grid above: Model · Samples · Rigs -->
	{#if arch || imgsz || samples !== null || machineCount !== null}
		<div class="grid grid-cols-3 gap-px bg-[var(--color-border)]">
			<div class="bg-[var(--color-surface)] px-3 py-2">
				<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Model</div>
				<div class="font-mono text-sm font-semibold text-[var(--color-text)]">
					{#if arch && imgsz}{arch} @ {imgsz}
					{:else if arch}{arch}
					{:else if imgsz}{imgsz}×{imgsz}
					{:else}—{/if}
				</div>
			</div>
			<div class="bg-[var(--color-surface)] px-3 py-2">
				<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Samples</div>
				<div class="font-mono text-sm font-semibold text-[var(--color-text)]">
					{samples !== null ? samples.toLocaleString() : '—'}
				</div>
			</div>
			<div
				class="bg-[var(--color-surface)] px-3 py-2"
				title={machineCount !== null
					? `Normalized Shannon entropy of per-machine sample shares across ${machineCount} rigs. 0 = single rig, 1.0 = perfect even split.`
					: 'Normalized Shannon entropy of per-machine sample shares. 0 = single rig, 1.0 = perfect even split.'}
			>
				<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Diversity</div>
				<div class="font-mono text-sm font-semibold text-[var(--color-text)]">
					{diversityScore !== null ? diversityScore.toFixed(3) : '—'}
				</div>
			</div>
		</div>
	{:else if model.description}
		<p class="line-clamp-2 px-4 py-3 text-xs text-[var(--color-text-muted)]">{model.description}</p>
	{/if}
</a>
