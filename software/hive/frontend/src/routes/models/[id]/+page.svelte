<script lang="ts">
	import { page } from '$app/state';
	import { api, type DetectionModelDetail, type DetectionModelVariant } from '$lib/api';
	import ModelTrainingReport from '$lib/components/ModelTrainingReport.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let model = $state<DetectionModelDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		const id = page.params.id;
		if (!id) return;
		void load(id);
	});

	async function load(id: string) {
		loading = true;
		error = null;
		try {
			model = await api.getModel(id);
		} catch (err: unknown) {
			const apiErr = err as { error?: string };
			error = apiErr?.error || 'Failed to load model';
		} finally {
			loading = false;
		}
	}

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

	const meta = $derived(asRecord(model?.training_metadata));
	const modelMeta = $derived(asRecord(meta?.model));
	const datasetMeta = $derived(asRecord(meta?.dataset));
	const best = $derived(asRecord(modelMeta?.best_metrics));

	const map50 = $derived(asNumber(best?.mAP50));
	const map50_95 = $derived(asNumber(best?.mAP50_95));
	const recall = $derived(asNumber(best?.recall));
	const precision = $derived(asNumber(best?.precision));

	const samples = $derived(asInt(datasetMeta?.total) ?? asInt(datasetMeta?.train_samples));
	const machineCount = $derived(asInt(asRecord(datasetMeta?.machines)?.count));

	const arch = $derived(typeof modelMeta?.architecture === 'string' ? (modelMeta.architecture as string) : null);
	const imgsz = $derived(asInt(modelMeta?.imgsz));

	// Same diversity-score formula as the card — Shannon entropy of per-machine shares.
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

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	function downloadUrl(variantId: string): string {
		return model ? api.modelVariantDownloadUrl(model.id, variantId) : '#';
	}

	// Color accent per runtime so the download tiles read at a glance.
	const runtimeAccent: Record<string, string> = {
		onnx: 'var(--color-info)',
		ncnn: 'var(--color-success)',
		pytorch: 'var(--color-primary)',
		rknn: '#9333EA',  // purple — Rockchip / Orange Pi
		hailo: 'var(--color-warning)',
		tflite: 'var(--color-warning)'
	};

	function variantAccent(variant: DetectionModelVariant): string {
		return runtimeAccent[variant.runtime.toLowerCase()] ?? 'var(--color-text-muted)';
	}

	// Short hint of where each runtime usually deploys, shown under the runtime label.
	const runtimeTarget: Record<string, string> = {
		onnx: 'Universal · CPU/GPU/Edge',
		ncnn: 'Mobile · ARM CPU',
		pytorch: 'Reference · GPU',
		rknn: 'Orange Pi 5 · RK3588 NPU',
		hailo: 'Hailo-8 NPU',
		tflite: 'TensorFlow Lite'
	};

	const runtimeDefaultExt: Record<string, string> = {
		onnx: '.onnx',
		ncnn: '.bin',
		hailo: '.hef',
		pytorch: '.pt',
		rknn: '.rknn'
	};

	function downloadFilename(variant: DetectionModelVariant): string {
		if (!model) return variant.file_name;
		const lastDot = (variant.file_name || '').lastIndexOf('.');
		let suffix = lastDot >= 0 ? variant.file_name.slice(lastDot) : '';
		if (variant.file_name?.endsWith('.tar.gz')) suffix = '.tar.gz';
		if (!suffix) suffix = runtimeDefaultExt[variant.runtime.toLowerCase()] ?? '';
		const date = model.published_at ? new Date(model.published_at).toISOString().slice(0, 10) : '';
		return `${model.slug}_v${model.version}${date ? `_${date}` : ''}_${variant.runtime}${suffix}`;
	}
</script>

<div class="space-y-4">
	<a href="/models" class="inline-flex items-center gap-1 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← Back to models</a>

	{#if loading}
		<div class="flex justify-center py-12"><Spinner /></div>
	{:else if error}
		<div class="border border-primary bg-primary-light p-3 text-sm text-primary">{error}</div>
	{:else if model}
		<!-- Hero — same DNA as ModelCard but bigger -->
		<div class="border border-[var(--color-border)] bg-[var(--color-surface)]">
			<!-- items-stretch + aspect-square on the swatch makes its height auto-match the
				 text block's natural height (codename H1 + slug + name = ~3 lines) so the
				 dot reads as a hero element proportional to its label. -->
			<div class="flex items-stretch gap-4 border-b border-[var(--color-border)] px-5 py-4">
				{#if model.codename_color}
					<div class="flex shrink-0 items-center">
						<span
							class="block aspect-square w-20 rounded-full border border-[var(--color-border)]"
							style="background-color: {model.codename_color}"
							aria-hidden="true"
						></span>
					</div>
				{/if}
				<div class="min-w-0 flex-1 self-center">
					{#if model.codename}
						<h1 class="text-3xl font-bold leading-tight tracking-tight text-[var(--color-text)]">{model.codename}</h1>
					{:else}
						<h1 class="text-2xl font-semibold tracking-tight text-[var(--color-text)]">{model.name}</h1>
					{/if}
					<p class="mt-1 font-mono text-xs text-[var(--color-text-muted)]">
						{model.slug} · v{model.version} · {relativeTime(model.published_at)}
					</p>
					{#if model.codename && model.name}
						<p class="mt-0.5 text-sm text-[var(--color-text-muted)]">{model.name}</p>
					{/if}
				</div>
				{#if !model.is_public}
					<span class="self-start border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-0.5 text-[11px] uppercase tracking-wider text-[var(--color-text-muted)]">Private</span>
				{/if}
			</div>

			<!-- Metric pills — 4 columns including Precision, since the detail page has room -->
			{#if map50 !== null || map50_95 !== null || precision !== null || recall !== null}
				<div class="grid grid-cols-4 gap-px border-b border-[var(--color-border)] bg-[var(--color-border)]">
					<div class="bg-[var(--color-surface)] px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">mAP50</div>
						<div class="font-mono text-lg font-semibold text-[var(--color-text)]">{formatPct(map50)}</div>
					</div>
					<div class="bg-[var(--color-surface)] px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">mAP50_95</div>
						<div class="font-mono text-lg font-semibold text-[var(--color-text)]">{formatPct(map50_95)}</div>
					</div>
					<div class="bg-[var(--color-surface)] px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Precision</div>
						<div class="font-mono text-lg font-semibold text-[var(--color-text)]">{formatPct(precision)}</div>
					</div>
					<div class="bg-[var(--color-surface)] px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Recall</div>
						<div class="font-mono text-lg font-semibold text-[var(--color-text)]">{formatPct(recall)}</div>
					</div>
				</div>
			{/if}

			<!-- Spec pills: Model / Samples / Diversity -->
			{#if arch || imgsz || samples !== null || diversityScore !== null}
				<div class="grid grid-cols-3 gap-px bg-[var(--color-border)]">
					<div class="bg-[var(--color-surface)] px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Model</div>
						<div class="font-mono text-base font-semibold text-[var(--color-text)]">
							{#if arch && imgsz}{arch} @ {imgsz}
							{:else if arch}{arch}
							{:else if imgsz}{imgsz}×{imgsz}
							{:else}—{/if}
						</div>
					</div>
					<div class="bg-[var(--color-surface)] px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Samples</div>
						<div class="font-mono text-base font-semibold text-[var(--color-text)]">
							{samples !== null ? samples.toLocaleString() : '—'}
						</div>
					</div>
					<div
						class="bg-[var(--color-surface)] px-4 py-3"
						title={machineCount !== null
							? `Normalized Shannon entropy of per-machine sample shares across ${machineCount} rigs. 0 = single rig, 1.0 = perfect even split.`
							: 'Normalized Shannon entropy of per-machine sample shares. 0 = single rig, 1.0 = perfect even split.'}
					>
						<div class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Diversity</div>
						<div class="font-mono text-base font-semibold text-[var(--color-text)]">
							{diversityScore !== null ? diversityScore.toFixed(3) : '—'}
						</div>
					</div>
				</div>
			{/if}
		</div>

		<!-- Downloads — one visible tile per variant. No dropdown -->
		{#if model.variants.length > 0}
			<section class="border border-[var(--color-border)] bg-[var(--color-surface)]">
				<div class="flex items-baseline justify-between border-b border-[var(--color-border)] px-5 py-3">
					<h2 class="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">Downloads</h2>
					<span class="text-xs text-[var(--color-text-muted)]">{model.variants.length} variant{model.variants.length === 1 ? '' : 's'}</span>
				</div>
				<div class="grid grid-cols-1 gap-px bg-[var(--color-border)] sm:grid-cols-2 lg:grid-cols-4">
					{#each model.variants as variant (variant.id)}
						<a
							href={downloadUrl(variant.id)}
							class="group relative block bg-[var(--color-surface)] p-4 transition-colors hover:bg-[var(--color-bg)]"
							download={downloadFilename(variant)}
						>
							<span class="absolute inset-y-0 left-0 w-1" style="background-color: {variantAccent(variant)};"></span>
							<div class="pl-3">
								<div class="flex items-baseline justify-between gap-2">
									<span class="font-mono text-sm font-bold uppercase tracking-wider" style="color: {variantAccent(variant)};">
										{variant.runtime}
									</span>
									<span class="text-xs tabular-nums text-[var(--color-text-muted)]">{formatSize(variant.file_size)}</span>
								</div>
								{#if runtimeTarget[variant.runtime.toLowerCase()]}
									<p class="mt-0.5 text-[11px] text-[var(--color-text-muted)]">{runtimeTarget[variant.runtime.toLowerCase()]}</p>
								{/if}
								<div class="mt-2 truncate font-mono text-[10px] text-[var(--color-text)]" title={downloadFilename(variant)}>
									{downloadFilename(variant)}
								</div>
								<div class="mt-0.5 font-mono text-[9px] text-[var(--color-text-muted)]" title={variant.sha256}>
									sha256 {variant.sha256.slice(0, 12)}…
								</div>
							</div>
						</a>
					{/each}
				</div>
			</section>
		{/if}

		<!-- Description + scopes — secondary detail, collapse to single line -->
		{#if model.description || (model.scopes && model.scopes.length > 0)}
			<section class="border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
				{#if model.description}
					<p class="text-sm text-[var(--color-text)]">{model.description}</p>
				{/if}
				{#if model.scopes && model.scopes.length > 0}
					<div class="mt-3 flex flex-wrap items-center gap-1">
						<span class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Scopes:</span>
						{#each model.scopes as scope (scope)}
							<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--color-text)]">{scope}</span>
						{/each}
					</div>
				{/if}
			</section>
		{/if}

		<!-- Deep-dive training report (existing component, untouched) -->
		{#if model.training_metadata}
			<ModelTrainingReport metadata={model.training_metadata} />
		{/if}
	{/if}
</div>
