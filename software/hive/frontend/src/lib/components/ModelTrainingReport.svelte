<script lang="ts">
	interface Props {
		metadata: Record<string, unknown>;
	}

	let { metadata }: Props = $props();

	type Row = Record<string, unknown>;

	function record(value: unknown): Row {
		return value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
	}

	function rows(value: unknown): Row[] {
		return Array.isArray(value) ? value.filter((item): item is Row => !!item && typeof item === 'object') : [];
	}

	function numberValue(value: unknown): number | null {
		const parsed = typeof value === 'number' ? value : Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}

	function textValue(value: unknown): string {
		return value === null || value === undefined ? '—' : String(value);
	}

	function pct(value: unknown, digits = 1): string {
		const num = numberValue(value);
		if (num === null) return '—';
		return `${(num * 100).toFixed(digits)}%`;
	}

	function num(value: unknown, digits = 3): string {
		const parsed = numberValue(value);
		if (parsed === null) return '—';
		return parsed.toFixed(digits);
	}

	function int(value: unknown): string {
		const parsed = numberValue(value);
		if (parsed === null) return '—';
		return Math.round(parsed).toLocaleString();
	}

	function clampPct(value: unknown): number {
		const parsed = numberValue(value);
		if (parsed === null) return 0;
		return Math.max(0, Math.min(100, parsed <= 1 ? parsed * 100 : parsed));
	}

	function formatSize(bytes: unknown): string {
		const b = numberValue(bytes);
		if (b === null) return '—';
		if (b < 1024) return `${b} B`;
		if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
		if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`;
		return `${(b / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	const model = $derived(record(metadata.model));
	const dataset = $derived(record(metadata.dataset));
	const datasetSelection = $derived(record(dataset.selection));
	const precheck = $derived(record(metadata.precheck));
	const precheckTotals = $derived(record(precheck.totals));
	const audit = $derived(record(metadata.audit));
	const auditManifest = $derived(record(audit.manifest));
	const auditRows = $derived(rows(audit.summaries));
	const spectrumRows = $derived(rows(metadata.count_spectrum));
	const roleCoverage = $derived(record(precheck.bucket_coverage_by_role));
	const sourceRoleCounts = $derived(record(datasetSelection.source_role_counts));
	const pieceCounts = $derived(record(datasetSelection.piece_count_counts));
	const bestMetrics = $derived(record(model.best_metrics));
	const modelTraining = $derived(record(model.training));
	const benchmarks = $derived(record(metadata.benchmarks));
	const variantSizes = $derived(record(metadata.variant_sizes_bytes));

	const auditPrimary = $derived(
		auditRows.find((row) => numberValue(row.threshold) === 0.25) ?? auditRows[0] ?? {}
	);
	const spectrumPrimary = $derived(spectrumRows.filter((row) => numberValue(row.threshold) === 0.25));

	function roleCoverageRows(): Row[] {
		return Object.entries(roleCoverage).map(([role, value]) => ({ role, ...record(value) }));
	}

	function sourceRows(): Row[] {
		const selected = record(sourceRoleCounts.selected);
		const train = record(sourceRoleCounts.train);
		const val = record(sourceRoleCounts.val);
		const roles = new Set([...Object.keys(selected), ...Object.keys(train), ...Object.keys(val)]);
		return [...roles].sort().map((role) => ({
			role,
			selected: selected[role],
			train: train[role],
			val: val[role]
		}));
	}

	function pieceRows(): Row[] {
		const selected = record(pieceCounts.selected);
		const train = record(pieceCounts.train);
		const val = record(pieceCounts.val);
		const order = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9-12', '13+'];
		return order
			.filter((label) => selected[label] !== undefined || train[label] !== undefined || val[label] !== undefined)
			.map((bucket) => ({ bucket, selected: selected[bucket], train: train[bucket], val: val[bucket] }));
	}

	function maxValue(items: Row[], keys: string[]): number {
		let max = 0;
		for (const row of items) {
			for (const key of keys) {
				const value = numberValue(row[key]);
				if (value !== null && value > max) max = value;
			}
		}
		return max || 1;
	}

	const sourceData = $derived(sourceRows());
	const pieceData = $derived(pieceRows());
	const sourceMax = $derived(maxValue(sourceData, ['selected']));
	const pieceMax = $derived(maxValue(pieceData, ['selected']));
	const coverageRows = $derived(roleCoverageRows());

	const totalSelected = $derived(sourceData.reduce((acc, row) => acc + (numberValue(row.selected) ?? 0), 0));

	function gaugeColor(value: number): string {
		const base =
			value >= 85 ? 'var(--color-success)'
			: value >= 70 ? 'var(--color-info)'
			: value >= 50 ? 'var(--color-warning)'
			: 'var(--color-primary)';
		return `color-mix(in srgb, ${base} 55%, transparent)`;
	}

	function gaugeText(value: number): string {
		if (value >= 85) return 'var(--color-success)';
		if (value >= 70) return 'var(--color-info)';
		if (value >= 50) return 'var(--color-warning)';
		return 'var(--color-primary)';
	}

	const softInfo = 'color-mix(in srgb, var(--color-info) 55%, transparent)';
	const softSuccess = 'color-mix(in srgb, var(--color-success) 55%, transparent)';
	const softPrimary = 'color-mix(in srgb, var(--color-primary) 55%, transparent)';
	const softWarning = 'color-mix(in srgb, var(--color-warning) 70%, transparent)';

	type Metric = {
		label: string;
		value: string;
		caption: string;
		percent: number;
		accent: string;
	};

	// Benchmark providers — pick the fastest available for the headline card.
	const benchmarkProviders = $derived.by<Array<{ key: string; name: string; data: Row }>>(() => {
		const local = record(benchmarks.local_mac);
		const out: Array<{ key: string; name: string; data: Row }> = [];
		const coreml = record(local.coreml_onnxruntime);
		const cpu = record(local.cpu_onnxruntime);
		if (Object.keys(coreml).length) out.push({ key: 'coreml', name: 'CoreML', data: coreml });
		if (Object.keys(cpu).length) out.push({ key: 'cpu', name: 'CPU', data: cpu });
		return out;
	});
	const fastestProvider = $derived(
		benchmarkProviders
			.slice()
			.sort((a, b) => (numberValue(a.data.mean_ms) ?? Infinity) - (numberValue(b.data.mean_ms) ?? Infinity))[0]
	);

	const onnxBytes = $derived(numberValue(variantSizes.onnx));
	const ncnnBytes = $derived(numberValue(variantSizes.ncnn));
	const ptBytes = $derived(numberValue(variantSizes.pytorch));
	const variantCount = $derived([onnxBytes, ncnnBytes, ptBytes].filter((b) => b !== null && b > 0).length);

	const heroMetrics = $derived.by<Metric[]>(() => {
		const cards: Metric[] = [];
		if (numberValue(bestMetrics.mAP50_95) !== null) {
			cards.push({
				label: 'mAP50-95',
				value: num(bestMetrics.mAP50_95),
				caption: numberValue(bestMetrics.mAP50) !== null ? `mAP50 ${num(bestMetrics.mAP50)}` : 'validation',
				percent: clampPct(bestMetrics.mAP50_95),
				accent: softPrimary
			});
		}
		if (numberValue(dataset.train_samples) !== null) {
			const target = numberValue(datasetSelection.target_size) ?? (numberValue(dataset.train_samples) ?? 0) + (numberValue(dataset.val_samples) ?? 0);
			cards.push({
				label: 'Training Samples',
				value: int(target),
				caption: `${int(dataset.train_samples)} train · ${int(dataset.val_samples)} val`,
				percent: 100,
				accent: softWarning
			});
		}
		const fp = fastestProvider;
		if (fp) {
			cards.push({
				label: 'Inference',
				value: `${num(fp.data.mean_ms, 1)} ms`,
				caption: `${fp.name} · ${int(fp.data.fps_mean)} fps`,
				percent: Math.min(100, ((numberValue(fp.data.fps_mean) ?? 0) / 500) * 100),
				accent: softInfo
			});
		}
		if (onnxBytes !== null) {
			cards.push({
				label: 'Model Size',
				value: formatSize(onnxBytes),
				caption: `${variantCount} runtime${variantCount === 1 ? '' : 's'} · ONNX`,
				percent: Math.min(100, ((onnxBytes ?? 0) / (60 * 1024 * 1024)) * 100),
				accent: softSuccess
			});
		}
		if (auditRows.length > 0 && numberValue(auditPrimary.f1_iou50) !== null) {
			cards.push({
				label: 'Holdout F1',
				value: num(auditPrimary.f1_iou50),
				caption: `P ${pct(auditPrimary.precision_iou50, 0)} · R ${pct(auditPrimary.recall_iou50, 0)}`,
				percent: clampPct(auditPrimary.f1_iou50),
				accent: softInfo
			});
		}
		if (auditRows.length > 0 && numberValue(auditPrimary.decision_match_rate) !== null) {
			cards.push({
				label: 'Decision Match',
				value: pct(auditPrimary.decision_match_rate),
				caption: `${int(auditManifest.sample_count)} holdout images`,
				percent: clampPct(auditPrimary.decision_match_rate),
				accent: softSuccess
			});
		}
		return cards;
	});

	// Compact key-value chips for the training setup band
	type Chip = { label: string; value: string; mono?: boolean };
	const setupChips = $derived.by<Chip[]>(() => {
		const chips: Chip[] = [];
		const baseModel = model.source_model ?? modelTraining.base_model;
		if (baseModel) chips.push({ label: 'base', value: String(baseModel), mono: true });
		if (model.imgsz) chips.push({ label: 'imgsz', value: int(model.imgsz), mono: true });
		const bestEpoch = modelTraining.best_epoch ?? bestMetrics.epoch;
		const totalEpochs = modelTraining.total_epochs;
		if (bestEpoch && totalEpochs) {
			chips.push({ label: 'epochs', value: `${int(bestEpoch)} / ${int(totalEpochs)}`, mono: true });
		} else if (totalEpochs) {
			chips.push({ label: 'epochs', value: int(totalEpochs), mono: true });
		}
		if (modelTraining.elapsed_min) chips.push({ label: 'duration', value: `${num(modelTraining.elapsed_min, 0)} min` });
		if (dataset.name) chips.push({ label: 'dataset', value: String(dataset.name), mono: true });
		if (dataset.min_detection_score !== undefined && dataset.min_detection_score !== null) {
			chips.push({ label: 'min score', value: num(dataset.min_detection_score, 2), mono: true });
		}
		const maxEmpty = dataset.max_empty_fraction;
		if (numberValue(maxEmpty) !== null) {
			chips.push({ label: 'empties', value: pct(maxEmpty, 0), mono: true });
		}
		const family = model.family;
		if (family) chips.push({ label: 'family', value: String(family) });
		return chips;
	});

	// Inference table rows — one per provider that's present
	type PerfRow = {
		name: string;
		mean: number | null;
		p95: number | null;
		fps: number | null;
		median: number | null;
	};
	const perfRows = $derived<PerfRow[]>(
		benchmarkProviders.map(({ name, data }) => ({
			name,
			mean: numberValue(data.mean_ms),
			p95: numberValue(data.p95_ms),
			fps: numberValue(data.fps_mean),
			median: numberValue(data.median_ms)
		}))
	);
	const perfFpsMax = $derived(Math.max(1, ...perfRows.map((row) => row.fps ?? 0)));

	const auditMax = $derived(
		Math.max(
			1,
			...auditRows.flatMap((row) => [
				numberValue(row.precision_iou50) ?? 0,
				numberValue(row.recall_iou50) ?? 0,
				numberValue(row.f1_iou50) ?? 0
			])
		)
	);

	const showInference = $derived(perfRows.length > 0);
	const showAudit = $derived(auditRows.length > 0);
	const showSpectrum = $derived(spectrumPrimary.length > 0);
	const showCoverage = $derived(coverageRows.length > 0);
	const heroGridClass = $derived(
		heroMetrics.length >= 4 ? 'grid grid-cols-2 gap-3 lg:grid-cols-4'
		: heroMetrics.length === 3 ? 'grid grid-cols-1 gap-3 sm:grid-cols-3'
		: heroMetrics.length === 2 ? 'grid grid-cols-1 gap-3 sm:grid-cols-2'
		: 'grid grid-cols-1 gap-3'
	);
</script>

<div class="space-y-8">
	{#if heroMetrics.length > 0}
		<section>
			<div class={heroGridClass}>
				{#each heroMetrics as metric (metric.label)}
					<div class="relative overflow-hidden border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
						<div class="text-[11px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">{metric.label}</div>
						<div class="mt-2 text-3xl font-semibold tabular-nums text-[var(--color-text)]">{metric.value}</div>
						<div class="mt-1 text-xs text-[var(--color-text-muted)]">{metric.caption}</div>
						<div class="mt-3 h-1.5 w-full bg-[var(--color-bg)]">
							<div class="h-1.5" style={`width: ${metric.percent}%; background: ${metric.accent};`}></div>
						</div>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	{#if setupChips.length > 0}
		<section>
			<div class="border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3">
				<div class="flex flex-wrap gap-x-5 gap-y-2">
					{#each setupChips as chip (chip.label)}
						<div class="flex items-baseline gap-1.5">
							<span class="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">{chip.label}</span>
							<span class={`text-sm text-[var(--color-text)] ${chip.mono ? 'font-mono' : ''}`}>{chip.value}</span>
						</div>
					{/each}
				</div>
			</div>
		</section>
	{/if}

	{#if showAudit}
		<section>
			<div class="mb-3 flex items-baseline justify-between gap-3">
				<h2 class="text-sm font-semibold uppercase tracking-wide text-[var(--color-text)]">Detection Quality</h2>
				<span class="text-xs text-[var(--color-text-muted)]">
					{int(auditManifest.sample_count)} images · {int(auditManifest.positive_holdout_count)} pos · {int(auditManifest.empty_holdout_count)} empty
				</span>
			</div>
			<div class="border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
				<div class="mb-3 flex flex-wrap items-center gap-4 text-xs text-[var(--color-text-muted)]">
					<span class="flex items-center gap-1.5"><span class="inline-block h-2 w-4" style={`background: ${softInfo}`}></span>Precision</span>
					<span class="flex items-center gap-1.5"><span class="inline-block h-2 w-4" style={`background: ${softSuccess}`}></span>Recall</span>
					<span class="flex items-center gap-1.5"><span class="inline-block h-2 w-4" style={`background: ${softPrimary}`}></span>F1</span>
				</div>
				<div class="space-y-4">
					{#each auditRows as row (row.threshold)}
						<div>
							<div class="mb-1.5 flex items-baseline justify-between gap-3">
								<div class="text-xs font-mono text-[var(--color-text-muted)]">conf ≥ {num(row.threshold, 2)}</div>
								<div class="text-xs text-[var(--color-text-muted)]">
									Empty FP {int(row.empty_false_positive_samples)}/{int(row.empty_samples)} · IoU {num(row.matched_mean_iou, 3)}
								</div>
							</div>
							<div class="grid grid-cols-[7rem_1fr_4rem] items-center gap-3">
								<div class="text-xs text-[var(--color-text-muted)]">Precision</div>
								<div class="h-2.5 bg-[var(--color-bg)]">
									<div class="h-2.5" style={`width: ${((numberValue(row.precision_iou50) ?? 0) / auditMax) * 100}%; background: ${softInfo};`}></div>
								</div>
								<div class="text-right text-xs tabular-nums">{pct(row.precision_iou50)}</div>
							</div>
							<div class="mt-1 grid grid-cols-[7rem_1fr_4rem] items-center gap-3">
								<div class="text-xs text-[var(--color-text-muted)]">Recall</div>
								<div class="h-2.5 bg-[var(--color-bg)]">
									<div class="h-2.5" style={`width: ${((numberValue(row.recall_iou50) ?? 0) / auditMax) * 100}%; background: ${softSuccess};`}></div>
								</div>
								<div class="text-right text-xs tabular-nums">{pct(row.recall_iou50)}</div>
							</div>
							<div class="mt-1 grid grid-cols-[7rem_1fr_4rem] items-center gap-3">
								<div class="text-xs text-[var(--color-text-muted)]">F1</div>
								<div class="h-2.5 bg-[var(--color-bg)]">
									<div class="h-2.5" style={`width: ${((numberValue(row.f1_iou50) ?? 0) / auditMax) * 100}%; background: ${softPrimary};`}></div>
								</div>
								<div class="text-right text-xs tabular-nums">{num(row.f1_iou50)}</div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		</section>
	{/if}

	{#if showSpectrum}
		<section>
			<div class="mb-3 flex items-baseline justify-between gap-3">
				<h2 class="text-sm font-semibold uppercase tracking-wide text-[var(--color-text)]">Count Accuracy by Piece Count</h2>
				<span class="text-xs text-[var(--color-text-muted)]">Within ±1 count · conf 0.25</span>
			</div>
			<div class="border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
				<div class="space-y-2">
					{#each spectrumPrimary as row}
						{@const accuracy = clampPct(row.within_1_count_rate)}
						<div class="grid grid-cols-[5rem_1fr_4.5rem_5rem] items-center gap-3 text-sm">
							<div class="font-mono text-xs text-[var(--color-text-muted)]">{textValue(row.gt_count_bin)} pc</div>
							<div class="h-3 bg-[var(--color-bg)]">
								<div class="h-3" style={`width: ${accuracy}%; background: ${gaugeColor(accuracy)};`}></div>
							</div>
							<div class="text-right tabular-nums font-medium">{pct(row.within_1_count_rate)}</div>
							<div class="text-right text-xs text-[var(--color-text-muted)]">MAE {num(row.count_mae, 2)}</div>
						</div>
					{/each}
				</div>
			</div>
		</section>
	{/if}

	{#if showInference}
		<section>
			<div class="mb-3 flex items-baseline justify-between gap-3">
				<h2 class="text-sm font-semibold uppercase tracking-wide text-[var(--color-text)]">Inference Performance</h2>
				<span class="text-xs text-[var(--color-text-muted)]">ONNX Runtime · imgsz {textValue(model.imgsz)}</span>
			</div>
			<div class="border border-[var(--color-border)] bg-[var(--color-surface)]">
				<div class="grid grid-cols-[6rem_1fr_5rem_5rem_5rem] items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-2 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
					<div>Provider</div>
					<div>Throughput</div>
					<div class="text-right">Mean</div>
					<div class="text-right">P95</div>
					<div class="text-right">FPS</div>
				</div>
				{#each perfRows as row, i (row.name)}
					{@const widthPct = ((row.fps ?? 0) / perfFpsMax) * 100}
					<div class={`grid grid-cols-[6rem_1fr_5rem_5rem_5rem] items-center gap-3 px-4 py-2.5 ${i > 0 ? 'border-t border-[var(--color-border)]' : ''}`}>
						<div class="font-mono text-xs uppercase tracking-wide text-[var(--color-text)]">{row.name}</div>
						<div class="h-2 bg-[var(--color-bg)]">
							<div class="h-2" style={`width: ${widthPct}%; background: ${softInfo};`}></div>
						</div>
						<div class="text-right text-sm tabular-nums">{num(row.mean, 1)} ms</div>
						<div class="text-right text-xs tabular-nums text-[var(--color-text-muted)]">{num(row.p95, 1)} ms</div>
						<div class="text-right text-sm font-medium tabular-nums">{int(row.fps)}</div>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	{#if sourceData.length > 0 || pieceData.length > 0}
		<section>
			<div class="mb-3 flex items-baseline justify-between gap-3">
				<h2 class="text-sm font-semibold uppercase tracking-wide text-[var(--color-text)]">Dataset Composition</h2>
				{#if totalSelected > 0}
					<span class="text-xs text-[var(--color-text-muted)]">{int(totalSelected)} selected samples</span>
				{/if}
			</div>
			<div class="grid gap-4 lg:grid-cols-2">
				{#if sourceData.length > 0}
					<div class="border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
						<div class="mb-3 flex items-baseline justify-between gap-3">
							<h3 class="text-sm font-semibold text-[var(--color-text)]">Source Roles</h3>
							<span class="text-xs text-[var(--color-text-muted)]">{sourceData.length} {sourceData.length === 1 ? 'source' : 'sources'}</span>
						</div>
						<div class="space-y-2.5">
							{#each sourceData as row}
								{@const selected = numberValue(row.selected) ?? 0}
								{@const width = (selected / sourceMax) * 100}
								{@const share = totalSelected > 0 ? (selected / totalSelected) * 100 : 0}
								<div>
									<div class="mb-0.5 flex items-baseline justify-between gap-2">
										<span class="font-mono text-xs text-[var(--color-text)]">{textValue(row.role)}</span>
										<span class="text-xs tabular-nums text-[var(--color-text-muted)]">{int(row.selected)} · {share.toFixed(0)}%</span>
									</div>
									<div class="h-3 bg-[var(--color-bg)]">
										<div class="h-3" style={`width: ${width}%; background: ${softInfo};`}></div>
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if pieceData.length > 0}
					<div class="border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
						<div class="mb-3 flex items-baseline justify-between gap-3">
							<h3 class="text-sm font-semibold text-[var(--color-text)]">Piece Count Buckets</h3>
							<span class="text-xs text-[var(--color-text-muted)]">per image</span>
						</div>
						<div class="flex h-40 items-end gap-1">
							{#each pieceData as row}
								{@const selected = numberValue(row.selected) ?? 0}
								{@const h = Math.max(2, (selected / pieceMax) * 100)}
								<div class="flex flex-1 flex-col items-center gap-1">
									<div class="text-[10px] tabular-nums text-[var(--color-text-muted)]">{int(row.selected)}</div>
									<div class="w-full" style={`height: ${h}%; background: ${softInfo};`} title={`${row.bucket}: ${selected} samples`}></div>
								</div>
							{/each}
						</div>
						<div class="mt-1 flex gap-1">
							{#each pieceData as row}
								<div class="flex-1 text-center font-mono text-[10px] text-[var(--color-text-muted)]">{textValue(row.bucket)}</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		</section>
	{/if}

	{#if showCoverage}
		<section>
			<div class="mb-3 flex items-baseline justify-between gap-3">
				<h2 class="text-sm font-semibold uppercase tracking-wide text-[var(--color-text)]">Precheck Coverage</h2>
				<span class="text-xs text-[var(--color-text-muted)]">
					Accepted {int(precheckTotals.accepted_evaluated_roles)} · pos {int(precheckTotals.accepted_positive_evaluated_roles)} · empty {int(precheckTotals.accepted_empty_evaluated_roles)}
				</span>
			</div>
			<div class="grid gap-3 md:grid-cols-3">
				{#each coverageRows as row}
					{@const score = clampPct(row.score_percent)}
					<div class="border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
						<div class="mb-2 flex items-center justify-between gap-2">
							<span class="font-mono text-xs text-[var(--color-text)]">{textValue(row.role)}</span>
							<span class="text-sm font-semibold tabular-nums" style={`color: ${gaugeText(score)};`}>{num(row.score_percent, 1)}%</span>
						</div>
						<div class="h-2 bg-[var(--color-bg)]">
							<div class="h-2" style={`width: ${score}%; background: ${gaugeColor(score)};`}></div>
						</div>
						<div class="mt-2 text-xs text-[var(--color-text-muted)]">Target {int(row.bucket_target_samples)} per bucket</div>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	{#if showAudit || sourceData.length > 0 || pieceData.length > 0 || showSpectrum}
		<section>
			<h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--color-text)]">Detail Tables</h2>
			<div class="space-y-2">
				{#if showAudit}
					<details class="border border-[var(--color-border)] bg-[var(--color-surface)]">
						<summary class="cursor-pointer px-4 py-2.5 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-bg)]">Audit summary — precision / recall by threshold</summary>
						<div class="overflow-x-auto border-t border-[var(--color-border)]">
							<table class="w-full text-sm">
								<thead class="bg-[var(--color-bg)] text-left text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
									<tr>
										<th class="px-3 py-2">Conf</th>
										<th class="px-3 py-2">Precision</th>
										<th class="px-3 py-2">Recall</th>
										<th class="px-3 py-2">F1</th>
										<th class="px-3 py-2">Mean IoU</th>
										<th class="px-3 py-2">Decision</th>
										<th class="px-3 py-2">Empty FP</th>
									</tr>
								</thead>
								<tbody>
									{#each auditRows as row}
										<tr class="border-t border-[var(--color-border)]">
											<td class="px-3 py-2 font-mono text-xs">{num(row.threshold, 2)}</td>
											<td class="px-3 py-2 tabular-nums">{pct(row.precision_iou50)}</td>
											<td class="px-3 py-2 tabular-nums">{pct(row.recall_iou50)}</td>
											<td class="px-3 py-2 tabular-nums">{num(row.f1_iou50)}</td>
											<td class="px-3 py-2 tabular-nums">{num(row.matched_mean_iou)}</td>
											<td class="px-3 py-2 tabular-nums">{pct(row.decision_match_rate)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.empty_false_positive_samples)} / {int(row.empty_samples)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</details>
				{/if}

				{#if sourceData.length > 0}
					<details class="border border-[var(--color-border)] bg-[var(--color-surface)]">
						<summary class="cursor-pointer px-4 py-2.5 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-bg)]">Dataset balance — source roles & splits</summary>
						<div class="overflow-x-auto border-t border-[var(--color-border)]">
							<table class="w-full text-sm">
								<thead class="bg-[var(--color-bg)] text-left text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
									<tr><th class="px-3 py-2">Source</th><th class="px-3 py-2">Selected</th><th class="px-3 py-2">Train</th><th class="px-3 py-2">Val</th></tr>
								</thead>
								<tbody>
									{#each sourceData as row}
										<tr class="border-t border-[var(--color-border)]">
											<td class="px-3 py-2 font-mono text-xs">{textValue(row.role)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.selected)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.train)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.val)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</details>
				{/if}

				{#if pieceData.length > 0}
					<details class="border border-[var(--color-border)] bg-[var(--color-surface)]">
						<summary class="cursor-pointer px-4 py-2.5 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-bg)]">Piece count buckets — splits</summary>
						<div class="overflow-x-auto border-t border-[var(--color-border)]">
							<table class="w-full text-sm">
								<thead class="bg-[var(--color-bg)] text-left text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
									<tr><th class="px-3 py-2">Bucket</th><th class="px-3 py-2">Selected</th><th class="px-3 py-2">Train</th><th class="px-3 py-2">Val</th></tr>
								</thead>
								<tbody>
									{#each pieceData as row}
										<tr class="border-t border-[var(--color-border)]">
											<td class="px-3 py-2 font-mono text-xs">{textValue(row.bucket)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.selected)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.train)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.val)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</details>
				{/if}

				{#if showSpectrum}
					<details class="border border-[var(--color-border)] bg-[var(--color-surface)]">
						<summary class="cursor-pointer px-4 py-2.5 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-bg)]">Count spectrum — within ±1 & MAE</summary>
						<div class="overflow-x-auto border-t border-[var(--color-border)]">
							<table class="w-full text-sm">
								<thead class="bg-[var(--color-bg)] text-left text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
									<tr><th class="px-3 py-2">GT count</th><th class="px-3 py-2">Within ±1</th><th class="px-3 py-2">MAE</th><th class="px-3 py-2">Samples</th></tr>
								</thead>
								<tbody>
									{#each spectrumPrimary as row}
										<tr class="border-t border-[var(--color-border)]">
											<td class="px-3 py-2 font-mono text-xs">{textValue(row.gt_count_bin)}</td>
											<td class="px-3 py-2 tabular-nums">{pct(row.within_1_count_rate)}</td>
											<td class="px-3 py-2 tabular-nums">{num(row.count_mae, 2)}</td>
											<td class="px-3 py-2 tabular-nums">{int(row.samples ?? row.sample_count)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</details>
				{/if}
			</div>
		</section>
	{/if}
</div>
