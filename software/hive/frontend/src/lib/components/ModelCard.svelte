<script lang="ts">
	import type { DetectionModelSummary } from '$lib/api';

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
	<!-- Header — codename swatch + codename H1 + slug/version/time meta -->
	<div class="flex items-start gap-3 border-b border-[var(--color-border)] px-4 py-3">
		{#if model.codename_color}
			<span
				class="mt-1 inline-block h-5 w-5 shrink-0 rounded-full border border-[var(--color-border)]"
				style="background-color: {model.codename_color}"
				aria-hidden="true"
			></span>
		{/if}
		<div class="min-w-0 flex-1">
			{#if model.codename}
				<h3 class="truncate text-xl font-bold text-[var(--color-text)]">{model.codename}</h3>
			{:else}
				<h3 class="truncate text-base font-semibold text-[var(--color-text)]">{model.name}</h3>
			{/if}
			<p class="truncate font-mono text-[11px] text-[var(--color-text-muted)]">
				{model.slug} · v{model.version} · {relativeTime(model.published_at)}
			</p>
		</div>
		{#if !model.is_public}
			<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Private</span>
		{/if}
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

	<!-- Body: architecture/imgsz row + dataset summary row -->
	<div class="space-y-1 px-4 py-3">
		{#if arch || imgsz}
			<p class="text-xs text-[var(--color-text)]">
				{#if arch}<span class="font-medium">{arch}</span>{/if}{#if arch && imgsz}<span class="text-[var(--color-text-muted)]"> · </span>{/if}{#if imgsz}<span class="text-[var(--color-text-muted)]">{imgsz}×{imgsz}</span>{/if}
			</p>
		{/if}
		{#if samples !== null || machineCount !== null}
			<p class="text-xs text-[var(--color-text-muted)]">
				{#if samples !== null}{samples.toLocaleString()} samples{/if}{#if samples !== null && machineCount !== null} · {/if}{#if machineCount !== null}{machineCount} rigs{/if}
			</p>
		{:else if model.description && !arch}
			<p class="line-clamp-2 text-xs text-[var(--color-text-muted)]">{model.description}</p>
		{/if}
	</div>
</a>
