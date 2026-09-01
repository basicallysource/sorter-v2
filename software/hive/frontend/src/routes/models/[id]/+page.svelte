<script lang="ts">
	import { page } from '$app/state';
	import {
		api,
		type DetectionModelDetail,
		type DetectionModelVariant,
		type ModelDatasetMachine
	} from '$lib/api';
	import { relativeTime } from '$lib/time';
	import ModelTrainingReport from '$lib/components/ModelTrainingReport.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let model = $state<DetectionModelDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	// Structured per-machine dataset composition (models published with sample
	// recording). Empty for older models — the metadata blob covers those.
	let datasetMachines = $state<ModelDatasetMachine[]>([]);
	let datasetRecorded = $state(0);

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
		try {
			const ds = await api.getModelDatasetMachines(id);
			datasetMachines = ds.machines;
			datasetRecorded = ds.total_recorded;
		} catch {
			// Non-fatal: page renders from training_metadata alone.
			datasetMachines = [];
			datasetRecorded = 0;
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

	// Rows for the Dataset Machines section: the structured per-sample recording
	// when the model has one, else parsed out of the metadata blob so older
	// models still show their composition.
	type MachineRow = {
		name: string;
		train: number | null;
		val: number | null;
		total: number;
		share: number;
	};
	const machineRows = $derived.by<MachineRow[]>(() => {
		if (datasetMachines.length > 0) {
			return datasetMachines.map((m) => ({
				name: m.machine_name,
				train: m.train_samples,
				val: m.val_samples,
				total: m.total,
				share: m.share
			}));
		}
		const dist = asRecord(asRecord(datasetMeta?.machines)?.distribution_after_balance);
		if (!dist) return [];
		const rows: MachineRow[] = [];
		for (const [name, value] of Object.entries(dist)) {
			const txt = typeof value === 'string' ? value : String(value);
			const match = txt.match(/(\d[\d.,]*)/);
			if (match)
				rows.push({
					name,
					train: null,
					val: null,
					total: parseInt(match[1].replace(/[.,]/g, ''), 10),
					share: 0
				});
		}
		const total = rows.reduce((acc, r) => acc + r.total, 0);
		for (const r of rows) r.share = total ? r.total / total : 0;
		return rows.sort((a, b) => b.total - a.total);
	});

	const machineCount = $derived(
		machineRows.length > 0 ? machineRows.length : asInt(asRecord(datasetMeta?.machines)?.count)
	);

	const arch = $derived(typeof modelMeta?.architecture === 'string' ? (modelMeta.architecture as string) : null);
	const imgsz = $derived(asInt(modelMeta?.imgsz));

	// Same diversity-score formula as the card — Shannon entropy of per-machine
	// shares — but fed from machineRows so it works for both sources.
	const diversityScore = $derived.by<number | null>(() => {
		const counts = machineRows.map((r) => r.total);
		if (counts.length < 2) return counts.length === 1 ? 0 : null;
		const total = counts.reduce((a, b) => a + b, 0);
		if (total === 0) return null;
		const shares = counts.map((c) => c / total);
		const entropy = -shares.reduce((acc, p) => acc + (p > 0 ? p * Math.log(p) : 0), 0);
		const maxEntropy = Math.log(counts.length);
		return maxEntropy > 0 ? entropy / maxEntropy : 0;
	});

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
	<a href="/models" class="inline-flex items-center gap-1 text-sm text-text-muted hover:text-text">← Back to models</a>

	{#if loading}
		<div class="flex justify-center py-12"><Spinner size={32} /></div>
	{:else if error}
		<div class="border border-primary bg-primary-light p-3 text-sm text-primary">{error}</div>
	{:else if model}
		<!-- Hero — same DNA as ModelCard but bigger -->
		<div class="border border-border bg-surface">
			<!-- items-stretch + aspect-square on the swatch makes its height auto-match the
				 text block's natural height (codename H1 + slug + name = ~3 lines) so the
				 dot reads as a hero element proportional to its label. -->
			<div class="flex flex-wrap items-stretch gap-4 border-b border-border px-4 py-4 sm:flex-nowrap sm:px-5">
				{#if model.codename_color}
					<div class="flex shrink-0 items-center">
						<span
							class="block aspect-square w-20 rounded-full border border-border"
							style="background-color: {model.codename_color}"
							aria-hidden="true"
						></span>
					</div>
				{/if}
				<div class="min-w-0 flex-1 self-center">
					{#if model.codename}
						<h1 class="text-3xl font-bold leading-tight tracking-tight text-text">{model.codename}</h1>
					{:else}
						<h1 class="text-2xl font-semibold tracking-tight text-text">{model.name}</h1>
					{/if}
					<p class="mt-1 font-mono text-xs text-text-muted">
						{model.slug} · v{model.version} · {relativeTime(model.published_at)}
					</p>
					{#if model.codename && model.name}
						<p class="mt-0.5 text-sm text-text-muted">{model.name}</p>
					{/if}
				</div>
				<div class="flex shrink-0 flex-col items-end gap-1 self-start">
					{#if model.experimental}
						<Badge text="Experimental" variant="warning" />
					{:else}
						<Badge text="Stable" variant="success" />
					{/if}
					{#if !model.is_public}
						<span class="border border-border bg-bg px-2 py-0.5 text-[11px] uppercase tracking-wider text-text-muted">Private</span>
					{/if}
				</div>
			</div>

			<!-- Metric pills — 4 columns including Precision, since the detail page has room -->
			{#if map50 !== null || map50_95 !== null || precision !== null || recall !== null}
				<div class="grid grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-4">
					<div class="bg-surface px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-text-muted">mAP50</div>
						<div class="font-mono text-lg font-semibold text-text">{formatPct(map50)}</div>
					</div>
					<div class="bg-surface px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-text-muted">mAP50_95</div>
						<div class="font-mono text-lg font-semibold text-text">{formatPct(map50_95)}</div>
					</div>
					<div class="bg-surface px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-text-muted">Precision</div>
						<div class="font-mono text-lg font-semibold text-text">{formatPct(precision)}</div>
					</div>
					<div class="bg-surface px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-text-muted">Recall</div>
						<div class="font-mono text-lg font-semibold text-text">{formatPct(recall)}</div>
					</div>
				</div>
			{/if}

			<!-- Spec pills: Model / Samples / Diversity -->
			{#if arch || imgsz || samples !== null || diversityScore !== null}
				<div class="grid grid-cols-2 gap-px bg-border sm:grid-cols-3">
					<div class="bg-surface px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-text-muted">Model</div>
						<div class="font-mono text-base font-semibold text-text">
							{#if arch && imgsz}{arch} @ {imgsz}
							{:else if arch}{arch}
							{:else if imgsz}{imgsz}×{imgsz}
							{:else}—{/if}
						</div>
					</div>
					<div class="bg-surface px-4 py-3">
						<div class="text-[10px] uppercase tracking-wider text-text-muted">Samples</div>
						<div class="font-mono text-base font-semibold text-text">
							{samples !== null ? samples.toLocaleString() : '—'}
						</div>
					</div>
					<div
						class="bg-surface px-4 py-3"
						title={machineCount !== null
							? `Normalized Shannon entropy of per-machine sample shares across ${machineCount} rigs. 0 = single rig, 1.0 = perfect even split.`
							: 'Normalized Shannon entropy of per-machine sample shares. 0 = single rig, 1.0 = perfect even split.'}
					>
						<div class="text-[10px] uppercase tracking-wider text-text-muted">Diversity</div>
						<div class="font-mono text-base font-semibold text-text">
							{diversityScore !== null ? diversityScore.toFixed(3) : '—'}
						</div>
					</div>
				</div>
			{/if}
		</div>

		<!-- Downloads — one visible tile per variant. No dropdown -->
		{#if model.variants.length > 0}
			<section class="border border-border bg-surface">
				<div class="flex items-baseline justify-between border-b border-border px-5 py-3">
					<h2 class="text-sm font-semibold uppercase tracking-wider text-text-muted">Downloads</h2>
					<span class="text-xs text-text-muted">{model.variants.length} variant{model.variants.length === 1 ? '' : 's'}</span>
				</div>
				<div class="grid grid-cols-1 gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
					{#each model.variants as variant (variant.id)}
						<a
							href={downloadUrl(variant.id)}
							class="group relative block bg-surface p-4 transition-colors hover:bg-bg"
							download={downloadFilename(variant)}
						>
							<span class="absolute inset-y-0 left-0 w-1" style="background-color: {variantAccent(variant)};"></span>
							<div class="pl-3">
								<div class="flex items-baseline justify-between gap-2">
									<span class="font-mono text-sm font-bold uppercase tracking-wider" style="color: {variantAccent(variant)};">
										{variant.runtime}
									</span>
									<span class="text-xs tabular-nums text-text-muted">{formatSize(variant.file_size)}</span>
								</div>
								{#if runtimeTarget[variant.runtime.toLowerCase()]}
									<p class="mt-0.5 text-[11px] text-text-muted">{runtimeTarget[variant.runtime.toLowerCase()]}</p>
								{/if}
								<div class="mt-2 truncate font-mono text-[10px] text-text" title={downloadFilename(variant)}>
									{downloadFilename(variant)}
								</div>
								<div class="mt-0.5 font-mono text-[9px] text-text-muted" title={variant.sha256}>
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
			<section class="border border-border bg-surface p-4">
				{#if model.description}
					<p class="text-sm text-text">{model.description}</p>
				{/if}
				{#if model.scopes && model.scopes.length > 0}
					<div class="mt-3 flex flex-wrap items-center gap-1">
						<span class="text-[10px] uppercase tracking-wider text-text-muted">Scopes:</span>
						{#each model.scopes as scope (scope)}
							<span class="border border-border bg-bg px-1.5 py-0.5 font-mono text-[11px] text-text">{scope}</span>
						{/each}
					</div>
				{/if}
			</section>
		{/if}

		<!-- Machines in the dataset — structured per-sample recording when present,
			 else derived from the training_metadata blob -->
		{#if machineRows.length > 0}
			<section class="border border-border bg-surface">
				<div class="flex items-baseline justify-between border-b border-border px-5 py-3">
					<h2 class="text-sm font-semibold uppercase tracking-wider text-text-muted">Dataset machines</h2>
					<span class="text-xs text-text-muted">
						{machineRows.length} machine{machineRows.length === 1 ? '' : 's'}{#if datasetRecorded > 0}&nbsp;· {datasetRecorded.toLocaleString()} samples recorded{/if}
					</span>
				</div>
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-border text-left text-[10px] uppercase tracking-wider text-text-muted">
								<th class="px-5 py-2 font-medium">Machine</th>
								<th class="px-3 py-2 text-right font-medium">Train</th>
								<th class="px-3 py-2 text-right font-medium">Val</th>
								<th class="px-3 py-2 text-right font-medium">Total</th>
								<th class="w-1/3 px-5 py-2 font-medium">Share</th>
							</tr>
						</thead>
						<tbody>
							{#each machineRows as row (row.name)}
								<tr class="border-b border-border last:border-b-0">
									<td class="px-5 py-2 text-text">{row.name}</td>
									<td class="px-3 py-2 text-right font-mono tabular-nums text-text-muted">
										{row.train !== null ? row.train.toLocaleString() : '—'}
									</td>
									<td class="px-3 py-2 text-right font-mono tabular-nums text-text-muted">
										{row.val !== null ? row.val.toLocaleString() : '—'}
									</td>
									<td class="px-3 py-2 text-right font-mono font-semibold tabular-nums text-text">
										{row.total.toLocaleString()}
									</td>
									<td class="px-5 py-2">
										<div class="flex items-center gap-2">
											<div class="h-1.5 flex-1 bg-bg">
												<div class="h-full bg-primary" style="width: {(row.share * 100).toFixed(1)}%"></div>
											</div>
											<span class="w-12 text-right font-mono text-[11px] tabular-nums text-text-muted">
												{(row.share * 100).toFixed(1)}%
											</span>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if datasetRecorded === 0}
					<p class="border-t border-border px-5 py-2 text-[11px] text-text-muted">
						From training metadata — this model predates per-sample dataset recording.
					</p>
				{/if}
			</section>
		{/if}

		<!-- Deep-dive training report (existing component, untouched) -->
		{#if model.training_metadata}
			<ModelTrainingReport metadata={model.training_metadata} />
		{/if}
	{/if}
</div>
