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
	import Alert from '$lib/components/Alert.svelte';
	import { auth } from '$lib/auth.svelte';
	import Star from '@lucide/svelte/icons/star';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Download from '@lucide/svelte/icons/download';
	import { sentence } from '$lib/text';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Stat from '$lib/components/Stat.svelte';

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
		return v === null ? '-' : v.toFixed(3);
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	// The default a fresh install with no account downloads for its runtime.
	let savingDefault = $state<string | null>(null);
	let defaultError = $state<string | null>(null);

	async function toggleDefault(variant: DetectionModelVariant, input: HTMLInputElement) {
		if (!model) return;
		const isDefault = model.default_for.includes(variant.runtime);
		savingDefault = variant.runtime;
		defaultError = null;
		try {
			if (isDefault) {
				await api.clearModelDefault(model.purpose, variant.runtime);
				model.default_for = model.default_for.filter((r) => r !== variant.runtime);
			} else {
				await api.setModelDefault(model.purpose, variant.runtime, model.id, variant.id);
				model.default_for = [...model.default_for, variant.runtime].sort();
			}
		} catch (err: unknown) {
			defaultError = (err as { error?: string })?.error || 'Failed to update the default';
		} finally {
			savingDefault = null;
			// The box shows what the server holds, not the click that failed.
			input.checked = model.default_for.includes(variant.runtime);
		}
	}

	function downloadUrl(variantId: string): string {
		return model ? api.modelVariantDownloadUrl(model.id, variantId) : '#';
	}


	// Short hint of where each runtime usually deploys, shown under the runtime label.
	const runtimeTarget: Record<string, string> = {
		onnx: 'Anywhere: CPU, GPU or edge',
		ncnn: 'ARM processors',
		pytorch: 'The reference, on a GPU',
		rknn: 'Orange Pi 5, the RK3588 NPU',
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

<svelte:head>
	<title>{model ? (model.codename ?? model.name) : 'Model'} - Hive</title>
</svelte:head>

<div>
	<Button href="/models" size="sm" variant="ghost" icon={ArrowLeft}>Models</Button>
</div>

{#if loading}
	<div class="flex justify-center py-12"><Spinner size={32} /></div>
{:else if error}
	<Alert tone="danger">{error}</Alert>
{:else if model}
	<div class="flex flex-col gap-(--gap-panels)">
		<div class="flex items-start gap-4">
			{#if model.codename_color}
				<span class="size-14 shrink-0 rounded-control" style="background-color: {model.codename_color}" aria-hidden="true"></span>
			{/if}
			<div class="min-w-0 flex-1">
				<PageHeader
					title={model.codename ?? model.name}
					description={model.codename && model.name ? model.name : undefined}
				>
					<div class="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
						<Badge tone={model.experimental ? 'warning' : 'success'}>{model.experimental ? 'Experimental' : 'Stable'}</Badge>
						{#if !model.is_public}<Badge>Private</Badge>{/if}
						<span><span class="font-mono">{model.slug}</span>, v{model.version}, {relativeTime(model.published_at)}</span>
					</div>
				</PageHeader>
			</div>
		</div>

		{#if map50 !== null || map50_95 !== null || precision !== null || recall !== null || arch || imgsz || samples !== null || diversityScore !== null}
			<section aria-label="Numbers" class="overflow-hidden rounded-panel bg-surface">
				<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
					<div class="border-t border-l border-line"><Stat label="mAP50" value={formatPct(map50)} /></div>
					<div class="border-t border-l border-line"><Stat label="mAP50-95" value={formatPct(map50_95)} /></div>
					<div class="border-t border-l border-line"><Stat label="Precision" value={formatPct(precision)} /></div>
					<div class="border-t border-l border-line"><Stat label="Recall" value={formatPct(recall)} /></div>
					<div class="border-t border-l border-line">
						<Stat
							label="Model"
							value={arch && imgsz ? `${arch} @ ${imgsz}` : (arch ?? (imgsz ? `${imgsz} x ${imgsz}` : '-'))}
						/>
					</div>
					<div class="border-t border-l border-line">
						<Stat label="Samples" value={samples !== null ? samples.toLocaleString() : '-'} />
					</div>
					<div class="col-span-2 border-t border-l border-line">
						<Stat label="Diversity" value={diversityScore !== null ? diversityScore.toFixed(3) : '-'} />
						<p class="-mt-2 px-5 pb-4 text-sm text-ink-muted">
							{machineCount !== null
								? `How evenly the samples come from ${machineCount} machines: 0 is one machine, 1 an even split.`
								: 'How evenly the samples come from different machines: 0 is one machine, 1 an even split.'}
						</p>
					</div>
				</div>
			</section>
		{/if}

		{#if model.variants.length > 0}
			<Panel title="Downloads" flush>
				{#snippet actions()}
					<span class="num text-sm text-ink-muted"
						>{model!.variants.length} variant{model!.variants.length === 1 ? '' : 's'}</span
					>
				{/snippet}
				{#if defaultError}
					<div class="px-(--pad-panel) pb-3"><Alert tone="danger">{defaultError}</Alert></div>
				{/if}
				<div class="-ml-px grid grid-cols-[repeat(auto-fit,minmax(15rem,1fr))]">
					{#each model.variants as variant (variant.id)}
						{@const isDefault = model.default_for.includes(variant.runtime)}
						<div class="flex flex-col border-t border-l border-line">
							<a
								href={downloadUrl(variant.id)}
								class="flex flex-1 flex-col gap-1 p-4 transition-colors hover:bg-hover"
								download={downloadFilename(variant)}
							>
								<span class="flex items-baseline justify-between gap-2">
									<span class="flex items-center gap-2 font-medium text-ink">
										<Download size={16} class="shrink-0 text-ink-muted" />{variant.runtime}
									</span>
									<span class="num text-sm text-ink-muted">{formatSize(variant.file_size)}</span>
								</span>
								{#if runtimeTarget[variant.runtime.toLowerCase()]}
									<span class="text-sm text-ink-muted">{runtimeTarget[variant.runtime.toLowerCase()]}</span>
								{/if}
								<span class="mt-1 truncate font-mono text-sm text-ink" title={downloadFilename(variant)}
									>{downloadFilename(variant)}</span
								>
								<span class="font-mono text-sm text-ink-faint" title={variant.sha256}
									>sha256 {variant.sha256.slice(0, 12)}...</span
								>
							</a>
							{#if auth.isAdmin}
								<div
									class="flex items-center gap-2 border-t border-line px-4 py-2 text-sm"
									title={model.is_public ? undefined : 'Only a public model can be a default: installs fetch it without signing in.'}
								>
									<Checkbox
										checked={isDefault}
										disabled={!model.is_public || savingDefault !== null}
										onchange={(e) => toggleDefault(variant, e.currentTarget as HTMLInputElement)}
										>Default for new {variant.runtime} installs</Checkbox
									>
									{#if savingDefault === variant.runtime}<Spinner size={12} />{/if}
								</div>
							{:else if isDefault}
								<div class="flex items-center gap-2 border-t border-line px-4 py-2 text-sm text-success-ink">
									<Star size={14} />Default for new {variant.runtime} installs
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</Panel>
		{/if}

		{#if model.description || (model.scopes && model.scopes.length > 0)}
			<Panel>
				{#if model.description}<p class="text-sm text-ink">{model.description}</p>{/if}
				{#if model.scopes && model.scopes.length > 0}
					<div class="mt-3 flex flex-wrap items-center gap-1.5">
						<span class="text-sm text-ink-muted">Scopes</span>
						{#each model.scopes as scope (scope)}<Badge>{sentence(scope)}</Badge>{/each}
					</div>
				{/if}
			</Panel>
		{/if}

		{#if machineRows.length > 0}
			<Panel
				title="Dataset machines"
				description={datasetRecorded === 0
					? 'From the training metadata: this model is older than per-sample dataset records.'
					: undefined}
				flush
			>
				{#snippet actions()}
					<span class="num text-sm text-ink-muted"
						>{machineRows.length} machine{machineRows.length === 1 ? '' : 's'}{#if datasetRecorded > 0}, {datasetRecorded.toLocaleString()}
							samples recorded{/if}</span
					>
				{/snippet}
				<div class="overflow-x-auto">
					<table class="data-table">
						<thead>
							<tr>
								<th>Machine</th>
								<th class="num">Train</th>
								<th class="num">Validation</th>
								<th class="num">Total</th>
								<th class="w-1/3">Share</th>
							</tr>
						</thead>
						<tbody>
							{#each machineRows as row (row.name)}
								<tr>
									<td>{row.name}</td>
									<td class="num text-ink-muted">{row.train !== null ? row.train.toLocaleString() : '-'}</td>
									<td class="num text-ink-muted">{row.val !== null ? row.val.toLocaleString() : '-'}</td>
									<td class="num font-medium">{row.total.toLocaleString()}</td>
									<td>
										<div class="flex items-center gap-2">
											<div class="flex-1">
												<ProgressBar label={`${row.name} share`} value={row.share * 100} />
											</div>
											<span class="num w-14 text-right text-ink-muted">{(row.share * 100).toFixed(1)}%</span>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</Panel>
		{/if}

		{#if model.training_metadata}
			<ModelTrainingReport metadata={model.training_metadata} />
		{/if}
	</div>
{/if}
