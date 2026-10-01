<script lang="ts">
	import { sentence } from '$lib/text';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Panel from '$lib/components/Panel.svelte';
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
		return value === null || value === undefined ? '-' : String(value);
	}

	function pct(value: unknown, digits = 1): string {
		const num = numberValue(value);
		if (num === null) return '-';
		return `${(num * 100).toFixed(digits)}%`;
	}

	function num(value: unknown, digits = 3): string {
		const parsed = numberValue(value);
		if (parsed === null) return '-';
		return parsed.toFixed(digits);
	}

	function int(value: unknown): string {
		const parsed = numberValue(value);
		if (parsed === null) return '-';
		return Math.round(parsed).toLocaleString();
	}

	function clampPct(value: unknown): number {
		const parsed = numberValue(value);
		if (parsed === null) return 0;
		return Math.max(0, Math.min(100, parsed <= 1 ? parsed * 100 : parsed));
	}

	function formatSize(bytes: unknown): string {
		const b = numberValue(bytes);
		if (b === null) return '-';
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

	// A score's bar and its number: the status tones, solid, on a track.
	function gaugeColor(value: number): string {
		return value >= 85 ? 'var(--success)' : value >= 70 ? 'var(--info)' : value >= 50 ? 'var(--warning)' : 'var(--danger)';
	}

	function gaugeText(value: number): string {
		return value >= 85
			? 'var(--success-ink)'
			: value >= 70
				? 'var(--info-ink)'
				: value >= 50
					? 'var(--warning-ink)'
					: 'var(--danger-ink)';
	}

	const softInfo = 'var(--info)';
	const softSuccess = 'var(--success)';
	const softPrimary = 'var(--primary)';
	const softWarning = 'var(--warning)';

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
				label: 'Training samples',
				value: int(target),
				caption: `${int(dataset.train_samples)} train, ${int(dataset.val_samples)} val`,
				percent: 100,
				accent: softWarning
			});
		}
		const fp = fastestProvider;
		if (fp) {
			cards.push({
				label: 'Inference',
				value: `${num(fp.data.mean_ms, 1)} ms`,
				caption: `${fp.name}, ${int(fp.data.fps_mean)} fps`,
				percent: Math.min(100, ((numberValue(fp.data.fps_mean) ?? 0) / 500) * 100),
				accent: softInfo
			});
		}
		if (onnxBytes !== null) {
			cards.push({
				label: 'Model size',
				value: formatSize(onnxBytes),
				caption: `${variantCount} runtime${variantCount === 1 ? '' : 's'}, ONNX`,
				percent: Math.min(100, ((onnxBytes ?? 0) / (60 * 1024 * 1024)) * 100),
				accent: softSuccess
			});
		}
		if (auditRows.length > 0 && numberValue(auditPrimary.f1_iou50) !== null) {
			cards.push({
				label: 'Holdout F1',
				value: num(auditPrimary.f1_iou50),
				caption: `P ${pct(auditPrimary.precision_iou50, 0)}, R ${pct(auditPrimary.recall_iou50, 0)}`,
				percent: clampPct(auditPrimary.f1_iou50),
				accent: softInfo
			});
		}
		if (auditRows.length > 0 && numberValue(auditPrimary.decision_match_rate) !== null) {
			cards.push({
				label: 'Decision match',
				value: pct(auditPrimary.decision_match_rate),
				caption: `${int(auditManifest.sample_count)} holdout images`,
				percent: clampPct(auditPrimary.decision_match_rate),
				accent: softSuccess
			});
		}
		return cards;
	});

	// Compact key-value chips for the training setup band
	// A name is set in the mono (someone may copy it); a number in tabular figures.
	type Chip = { label: string; value: string; kind?: 'mono' | 'num' };
	const setupChips = $derived.by<Chip[]>(() => {
		const chips: Chip[] = [];
		const baseModel = model.source_model ?? modelTraining.base_model;
		if (baseModel) chips.push({ label: 'base', value: String(baseModel), kind: 'mono' });
		if (model.imgsz) chips.push({ label: 'imgsz', value: int(model.imgsz), kind: 'num' });
		const bestEpoch = modelTraining.best_epoch ?? bestMetrics.epoch;
		const totalEpochs = modelTraining.total_epochs;
		if (bestEpoch && totalEpochs) {
			chips.push({ label: 'epochs', value: `${int(bestEpoch)} of ${int(totalEpochs)}`, kind: 'num' });
		} else if (totalEpochs) {
			chips.push({ label: 'epochs', value: int(totalEpochs), kind: 'num' });
		}
		if (modelTraining.elapsed_min) chips.push({ label: 'duration', value: `${num(modelTraining.elapsed_min, 0)} min`, kind: 'num' });
		if (dataset.name) chips.push({ label: 'dataset', value: String(dataset.name), kind: 'mono' });
		if (dataset.min_detection_score !== undefined && dataset.min_detection_score !== null) {
			chips.push({ label: 'min score', value: num(dataset.min_detection_score, 2), kind: 'num' });
		}
		const maxEmpty = dataset.max_empty_fraction;
		if (numberValue(maxEmpty) !== null) {
			chips.push({ label: 'empties', value: pct(maxEmpty, 0), kind: 'num' });
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
		heroMetrics.length >= 4 ? 'grid grid-cols-2 lg:grid-cols-4'
		: heroMetrics.length === 3 ? 'grid grid-cols-1 sm:grid-cols-3'
		: heroMetrics.length === 2 ? 'grid grid-cols-1 sm:grid-cols-2'
		: 'grid grid-cols-1'
	);
</script>

{#snippet bar(percent: number, color: string, height = 'h-2')}
	<div class="{height} w-full overflow-hidden rounded-badge bg-track">
		<div class="h-full" style={`width: ${percent}%; background: ${color};`}></div>
	</div>
{/snippet}

<div class="flex flex-col gap-(--gap-panels)">
	{#if heroMetrics.length > 0}
		<section aria-label="Headline numbers" class="overflow-hidden rounded-panel bg-surface">
			<div class="{heroGridClass} -mt-px -ml-px">
				{#each heroMetrics as metric (metric.label)}
					<div class="flex flex-col gap-1 border-t border-l border-line p-4">
						<div class="text-sm text-ink-muted">{metric.label}</div>
						<div class="num text-2xl font-medium text-ink">{metric.value}</div>
						<div class="text-sm text-ink-muted">{metric.caption}</div>
						<div class="mt-2">{@render bar(metric.percent, metric.accent, 'h-1.5')}</div>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	{#if setupChips.length > 0}
		<Panel>
			<dl class="flex flex-wrap gap-x-6 gap-y-2">
				{#each setupChips as chip (chip.label)}
					<div class="flex items-baseline gap-1.5">
						<dt class="text-sm text-ink-muted">{sentence(chip.label)}</dt>
						<dd class="text-sm text-ink {chip.kind === 'mono' ? 'font-mono' : chip.kind === 'num' ? 'num' : ''}">{chip.value}</dd>
					</div>
				{/each}
			</dl>
		</Panel>
	{/if}

	{#if showAudit}
		<Panel
			title="Detection quality"
			description={`${int(auditManifest.sample_count)} images: ${int(auditManifest.positive_holdout_count)} with pieces, ${int(auditManifest.empty_holdout_count)} empty.`}
		>
			<div class="mb-4 flex flex-wrap items-center gap-4 text-sm text-ink-muted">
				<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full" style={`background: ${softInfo}`}></span>Precision</span>
				<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full" style={`background: ${softSuccess}`}></span>Recall</span>
				<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full" style={`background: ${softPrimary}`}></span>F1</span>
			</div>
			<div class="flex flex-col gap-5">
				{#each auditRows as row (row.threshold)}
					<div>
						<div class="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
							<span class="num text-ink">Confidence {num(row.threshold, 2)} and up</span>
							<span class="text-ink-muted"
								>Empty false positives {int(row.empty_false_positive_samples)} of {int(row.empty_samples)}, IoU {num(
									row.matched_mean_iou,
									3
								)}</span
							>
						</div>
						{#each [
							{ label: 'Precision', value: row.precision_iou50, color: softInfo, text: pct(row.precision_iou50) },
							{ label: 'Recall', value: row.recall_iou50, color: softSuccess, text: pct(row.recall_iou50) },
							{ label: 'F1', value: row.f1_iou50, color: softPrimary, text: num(row.f1_iou50) }
						] as line (line.label)}
							<div class="mt-1 grid grid-cols-[6rem_1fr_4rem] items-center gap-3 text-sm">
								<span class="text-ink-muted">{line.label}</span>
								{@render bar(((numberValue(line.value) ?? 0) / auditMax) * 100, line.color, 'h-2.5')}
								<span class="num text-right text-ink">{line.text}</span>
							</div>
						{/each}
					</div>
				{/each}
			</div>
		</Panel>
	{/if}

	{#if showSpectrum}
		<Panel title="Count accuracy by piece count" description="Within one piece of the true count, at confidence 0.25.">
			<div class="flex flex-col gap-2">
				{#each spectrumPrimary as row, i (i)}
					{@const accuracy = clampPct(row.within_1_count_rate)}
					<div class="grid grid-cols-[3.5rem_1fr_3.5rem_4.5rem] items-center gap-2 text-sm sm:grid-cols-[5rem_1fr_4.5rem_5rem] sm:gap-3">
						<span class="num text-ink-muted">{textValue(row.gt_count_bin)} pieces</span>
						{@render bar(accuracy, gaugeColor(accuracy), 'h-3')}
						<span class="num text-right font-medium text-ink">{pct(row.within_1_count_rate)}</span>
						<span class="num text-right text-ink-muted">MAE {num(row.count_mae, 2)}</span>
					</div>
				{/each}
			</div>
		</Panel>
	{/if}

	{#if showInference}
		<Panel title="Inference speed" description={`ONNX Runtime at ${textValue(model.imgsz)} pixels.`} flush>
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr>
							<th>Provider</th>
							<th class="hidden w-1/3 sm:table-cell">Throughput</th>
							<th class="num">Mean</th>
							<th class="num">p95</th>
							<th class="num">Frames a second</th>
						</tr>
					</thead>
					<tbody>
						{#each perfRows as row (row.name)}
							<tr>
								<td class="font-mono">{row.name}</td>
								<td class="hidden sm:table-cell">{@render bar(((row.fps ?? 0) / perfFpsMax) * 100, softInfo)}</td>
								<td class="num whitespace-nowrap">{num(row.mean, 1)} ms</td>
								<td class="num whitespace-nowrap text-ink-muted">{num(row.p95, 1)} ms</td>
								<td class="num font-medium">{int(row.fps)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>
	{/if}

	{#if sourceData.length > 0 || pieceData.length > 0}
		<div class="grid gap-(--gap-panels) lg:grid-cols-2">
			{#if sourceData.length > 0}
				<Panel
					title="Source roles"
					description={totalSelected > 0 ? `${int(totalSelected)} samples chosen for the dataset.` : undefined}
				>
					<div class="flex flex-col gap-3">
						{#each sourceData as row, i (i)}
							{@const selected = numberValue(row.selected) ?? 0}
							<div>
								<div class="mb-1 flex items-baseline justify-between gap-2 text-sm">
									<span class="text-ink">{sentence(textValue(row.role))}</span>
									<span class="num text-ink-muted"
										>{int(row.selected)}, {(totalSelected > 0 ? (selected / totalSelected) * 100 : 0).toFixed(0)}%</span
									>
								</div>
								{@render bar((selected / sourceMax) * 100, softInfo, 'h-3')}
							</div>
						{/each}
					</div>
				</Panel>
			{/if}

			{#if pieceData.length > 0}
				<Panel title="Pieces in each picture">
					<div class="rounded-control bg-well p-3">
						<div class="flex h-40 items-end gap-1">
							{#each pieceData as row, i (i)}
								{@const selected = numberValue(row.selected) ?? 0}
								<div class="flex h-full flex-1 flex-col items-center justify-end gap-1">
									<span class="num text-xs text-ink-muted">{int(row.selected)}</span>
									<div
										class="w-full"
										style={`height: ${Math.max(2, (selected / pieceMax) * 100)}%; background: ${softInfo};`}
										title={`${row.bucket}: ${selected} samples`}
									></div>
								</div>
							{/each}
						</div>
						<div class="mt-1 flex gap-1">
							{#each pieceData as row, i (i)}
								<span class="num flex-1 text-center text-xs text-ink-muted">{textValue(row.bucket)}</span>
							{/each}
						</div>
					</div>
				</Panel>
			{/if}
		</div>
	{/if}

	{#if showCoverage}
		<Panel
			title="Precheck coverage"
			description={`Accepted ${int(precheckTotals.accepted_evaluated_roles)}: ${int(precheckTotals.accepted_positive_evaluated_roles)} with pieces, ${int(precheckTotals.accepted_empty_evaluated_roles)} empty.`}
			flush
		>
			<div class="-ml-px grid md:grid-cols-3">
				{#each coverageRows as row, i (i)}
					{@const score = clampPct(row.score_percent)}
					<div class="flex flex-col gap-2 border-t border-l border-line p-4">
						<div class="flex items-center justify-between gap-2 text-sm">
							<span class="text-ink">{sentence(textValue(row.role))}</span>
							<span class="num font-medium" style={`color: ${gaugeText(score)};`}>{num(row.score_percent, 1)}%</span>
						</div>
						{@render bar(score, gaugeColor(score))}
						<span class="text-sm text-ink-muted">Target {int(row.bucket_target_samples)} a bucket</span>
					</div>
				{/each}
			</div>
		</Panel>
	{/if}

	{#if showAudit || sourceData.length > 0 || pieceData.length > 0 || showSpectrum}
		<Panel title="Detail tables" flush>
			<div class="divide-y divide-line border-t border-line">
				{#if showAudit}
					<Disclosure title="Precision and recall by threshold">
						<div class="overflow-x-auto">
							<table class="data-table">
								<thead>
									<tr>
										<th class="num">Confidence</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">F1</th>
										<th class="num">Mean IoU</th><th class="num">Decision</th><th class="num">Empty false positives</th>
									</tr>
								</thead>
								<tbody>
									{#each auditRows as row, i (i)}
										<tr>
											<td class="num">{num(row.threshold, 2)}</td>
											<td class="num">{pct(row.precision_iou50)}</td>
											<td class="num">{pct(row.recall_iou50)}</td>
											<td class="num">{num(row.f1_iou50)}</td>
											<td class="num">{num(row.matched_mean_iou)}</td>
											<td class="num">{pct(row.decision_match_rate)}</td>
											<td class="num whitespace-nowrap">{int(row.empty_false_positive_samples)} of {int(row.empty_samples)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</Disclosure>
				{/if}
				{#if sourceData.length > 0}
					<Disclosure title="Dataset balance by source and split">
						<div class="overflow-x-auto">
							<table class="data-table">
								<thead>
									<tr><th>Source</th><th class="num">Chosen</th><th class="num">Train</th><th class="num">Validation</th></tr>
								</thead>
								<tbody>
									{#each sourceData as row, i (i)}
										<tr>
											<td>{sentence(textValue(row.role))}</td>
											<td class="num">{int(row.selected)}</td>
											<td class="num">{int(row.train)}</td>
											<td class="num">{int(row.val)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</Disclosure>
				{/if}
				{#if pieceData.length > 0}
					<Disclosure title="Pieces in each picture by split">
						<div class="overflow-x-auto">
							<table class="data-table">
								<thead>
									<tr><th>Pieces</th><th class="num">Chosen</th><th class="num">Train</th><th class="num">Validation</th></tr>
								</thead>
								<tbody>
									{#each pieceData as row, i (i)}
										<tr>
											<td class="num text-left!">{textValue(row.bucket)}</td>
											<td class="num">{int(row.selected)}</td>
											<td class="num">{int(row.train)}</td>
											<td class="num">{int(row.val)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</Disclosure>
				{/if}
				{#if showSpectrum}
					<Disclosure title="Count accuracy and error by piece count">
						<div class="overflow-x-auto">
							<table class="data-table">
								<thead>
									<tr><th>True count</th><th class="num">Within one</th><th class="num">MAE</th><th class="num">Samples</th></tr>
								</thead>
								<tbody>
									{#each spectrumPrimary as row, i (i)}
										<tr>
											<td class="num text-left!">{textValue(row.gt_count_bin)}</td>
											<td class="num">{pct(row.within_1_count_rate)}</td>
											<td class="num">{num(row.count_mae, 2)}</td>
											<td class="num">{int(row.samples ?? row.sample_count)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</Disclosure>
				{/if}
			</div>
		</Panel>
	{/if}
</div>
