<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import { Alert, Button } from '$lib/components/primitives';
	import { Gauge, Zap } from 'lucide-svelte';

	type Option = {
		id: string;
		label: string;
		available: boolean;
		reason?: string | null;
		rank: number;
		recommended?: boolean;
		detail?: string;
	};

	type Format = {
		id: string;
		label: string;
		extensions: string[];
		description: string;
		options: Option[];
	};

	type BenchResult = {
		fps: number;
		mean_ms: number;
		p50_ms: number;
		p90_ms: number;
		threads: number;
		error?: string;
	};

	type Variant = { local_id: string; variant_runtime: string | null };

	let {
		open = $bindable(false),
		modelName = '',
		variants = [],
		baseUrl
	}: {
		open?: boolean;
		modelName?: string;
		variants?: Variant[];
		baseUrl: string;
	} = $props();

	// Only these options have a real benchmark path on the backend. RKNN is now
	// single-stream vs 3-core fan-out — the per-core (core0/1/2) ids are gone.
	const BENCH_ONLY_OPTIONS = new Set([
		'onnx-cpu',
		'onnx-coreml',
		'onnx-cuda',
		'onnx-dml',
		'ncnn-cpu',
		'ncnn-vulkan',
		'rknn-npu-single',
		'rknn-npu-multi'
	]);

	// CPU paths are kept but visually de-emphasized — the accelerator/GPU path is
	// what the operator should actually run on.
	const CPU_OPTIONS = new Set(['onnx-cpu', 'ncnn-cpu']);

	let formats = $state<Format[]>([]);
	let cpuCores = $state(1);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let benchmarking = $state(false);
	let currentKey = $state<string | null>(null);
	// Keyed by `${option_id}@${threads}` → result.
	let results = $state<Record<string, BenchResult>>({});

	let loadedFor = $state<string | null>(null);

	function variantKey(): string {
		return variants.map((v) => `${v.local_id}:${v.variant_runtime ?? ''}`).join('|');
	}

	function formatIdFromVariant(variant: string | null | undefined): string | null {
		const v = (variant ?? '').toLowerCase();
		if (v.includes('onnx')) return 'onnx';
		if (v.includes('ncnn')) return 'ncnn';
		if (v.includes('rknn')) return 'rknn';
		if (v.includes('hef') || v.includes('hailo')) return 'hailo';
		if (v.includes('pt') || v.includes('torch')) return 'pytorch';
		return null;
	}

	// formatId → local_id of the installed variant we benchmark for that format.
	let localIdByFormat = $derived.by<Record<string, string>>(() => {
		const map: Record<string, string> = {};
		for (const v of variants) {
			const fid = formatIdFromVariant(v.variant_runtime);
			if (fid && !(fid in map)) map[fid] = v.local_id;
		}
		return map;
	});

	// Formats we can actually benchmark: this model has the artifact AND the
	// machine has at least one runnable backend for it.
	let benchFormats = $derived.by<Format[]>(() =>
		formats
			.filter((f) => f.id in localIdByFormat)
			.map((f) => ({
				...f,
				options: f.options.filter((o) => o.available && BENCH_ONLY_OPTIONS.has(o.id))
			}))
			.filter((f) => f.options.length > 0)
	);

	// The single best backend on this machine for this model — the accelerator/GPU
	// path the operator should prefer. Prefer an explicit `recommended` flag
	// (RKNN multi), else the lowest rank across every runnable option.
	let recommendedOptionId = $derived.by<string | null>(() => {
		const all = benchFormats.flatMap((f) => f.options);
		if (all.length === 0) return null;
		const flagged = all.find((o) => o.recommended);
		if (flagged) return flagged.id;
		return all.reduce((best, o) => (o.rank < best.rank ? o : best), all[0]).id;
	});

	async function load() {
		loading = true;
		error = null;
		try {
			const [fRes, cRes] = await Promise.all([
				fetch(`${baseUrl}/api/runtimes/formats`),
				fetch(`${baseUrl}/api/runtimes/capabilities`)
			]);
			if (!fRes.ok) throw new Error(`HTTP ${fRes.status}`);
			const payload = await fRes.json();
			formats = Array.isArray(payload?.formats) ? payload.formats : [];
			if (cRes.ok) {
				const caps = await cRes.json();
				const cores = Number(caps?.cpu?.cores ?? 0);
				if (cores > 0) cpuCores = cores;
			}
		} catch (e: any) {
			error = e?.message ?? 'Failed to load runtimes.';
			formats = [];
		} finally {
			loading = false;
		}
	}

	// (Re)load the capability matrix the first time the modal opens for a given
	// model, and reset stale results when the model changes.
	$effect(() => {
		if (!open) return;
		const key = variantKey();
		if (loadedFor !== key) {
			results = {};
			loadedFor = key;
			void load();
		}
	});

	function threadCountsFor(optionId: string): number[] {
		const max = Math.max(1, cpuCores);
		const half = Math.max(1, Math.floor(max / 2));
		if (optionId === 'onnx-cpu') {
			return Array.from(new Set([1, half, max])).sort((a, b) => a - b);
		}
		if (optionId === 'ncnn-cpu') {
			return Array.from(new Set([1, 3, half, max])).sort((a, b) => a - b);
		}
		return [1];
	}

	function resultKey(optionId: string, threads: number): string {
		return `${optionId}@${threads}`;
	}

	function fpsClass(fps: number): string {
		// 30-fps stream budget: 90 fps → 3 streams, 60 → 2, below → deficit.
		if (fps >= 90) return 'border-success bg-success/10 text-success-dark dark:text-success';
		if (fps >= 60) return 'border-warning bg-warning/10 text-warning-dark dark:text-warning';
		return 'border-danger bg-danger/10 text-danger-dark dark:text-danger';
	}

	async function runOne(formatId: string, optionId: string, threads: number) {
		const localId = localIdByFormat[formatId];
		if (!localId) return;
		const key = resultKey(optionId, threads);
		currentKey = key;
		try {
			const res = await fetch(`${baseUrl}/api/runtimes/benchmark`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					local_id: localId,
					option_id: optionId,
					threads,
					iterations: 40,
					warmup: 5
				})
			});
			if (!res.ok) {
				const text = await res.text().catch(() => '');
				results = {
					...results,
					[key]: { fps: 0, mean_ms: 0, p50_ms: 0, p90_ms: 0, threads, error: text.slice(0, 200) }
				};
				return;
			}
			const data = await res.json();
			results = {
				...results,
				[key]: {
					fps: data.fps ?? 0,
					mean_ms: data.mean_ms ?? 0,
					p50_ms: data.p50_ms ?? 0,
					p90_ms: data.p90_ms ?? 0,
					threads: data.threads ?? threads
				}
			};
		} catch (e: any) {
			results = {
				...results,
				[key]: { fps: 0, mean_ms: 0, p50_ms: 0, p90_ms: 0, threads, error: e?.message ?? 'failed' }
			};
		} finally {
			if (currentKey === key) currentKey = null;
		}
	}

	async function runOption(formatId: string, optionId: string) {
		if (benchmarking) return;
		benchmarking = true;
		try {
			for (const t of threadCountsFor(optionId)) {
				await runOne(formatId, optionId, t);
			}
		} finally {
			benchmarking = false;
			currentKey = null;
		}
	}

	async function runAll() {
		if (benchmarking) return;
		benchmarking = true;
		try {
			for (const fmt of benchFormats) {
				for (const opt of fmt.options) {
					for (const t of threadCountsFor(opt.id)) {
						await runOne(fmt.id, opt.id, t);
					}
				}
			}
		} finally {
			benchmarking = false;
			currentKey = null;
		}
	}

	function optionResults(optionId: string): { threads: number; r: BenchResult }[] {
		return threadCountsFor(optionId)
			.map((t) => ({ threads: t, r: results[resultKey(optionId, t)] }))
			.filter((x): x is { threads: number; r: BenchResult } => Boolean(x.r));
	}
</script>

<Modal bind:open title={`Benchmark · ${modelName}`} wide>
	<div class="flex flex-col gap-4">
		{#if loading}
			<div class="text-sm text-text-muted">Detecting runtimes…</div>
		{:else if error}
			<Alert variant="danger">{error}</Alert>
		{:else if benchFormats.length === 0}
			<Alert variant="info">
				No benchmarkable backend on this machine for the installed formats of this model.
			</Alert>
		{:else}
			<div class="flex flex-wrap items-center justify-between gap-3">
				<p class="max-w-2xl text-sm text-text-muted">
					Forward-pass throughput per backend, the way the sorter runs it. RKNN reports
					single-stream vs 3-core fan-out (aggregate). The recommended path is marked.
				</p>
				<Button variant="primary" size="sm" onclick={() => void runAll()} disabled={benchmarking}>
					<Gauge size={14} />
					<span>{benchmarking ? 'Benchmarking…' : 'Run all'}</span>
				</Button>
			</div>

			<div class="flex flex-col gap-4">
				{#each benchFormats as fmt (fmt.id)}
					<div class="border border-border bg-bg">
						<div
							class="flex items-center justify-between gap-2 border-b border-border bg-surface px-3 py-2"
						>
							<span class="text-sm font-semibold text-text">{fmt.label}</span>
							<span class="font-mono text-xs text-text-muted">{fmt.extensions.join(' / ')}</span>
						</div>
						<div class="flex flex-col divide-y divide-border">
							{#each fmt.options as opt (opt.id)}
								{@const isRecommended = opt.id === recommendedOptionId}
								{@const isCpu = CPU_OPTIONS.has(opt.id)}
								{@const rs = optionResults(opt.id)}
								<div
									class="flex flex-col gap-2 px-3 py-2.5"
									class:opacity-70={isCpu && !isRecommended}
								>
									<div class="flex flex-wrap items-center justify-between gap-2">
										<div class="flex min-w-0 items-center gap-2">
											<span class="text-sm font-medium text-text">{opt.label}</span>
											{#if isRecommended}
												<span
													class="inline-flex items-center gap-1 border border-primary px-1.5 py-0.5 text-xs font-semibold tracking-wider text-primary uppercase"
												>
													<Zap size={10} />
													Recommended
												</span>
											{/if}
											{#if isCpu}
												<span
													class="border border-border px-1.5 py-0.5 text-xs tracking-wider text-text-muted uppercase"
												>
													CPU fallback
												</span>
											{/if}
											{#if opt.detail}
												<span class="truncate text-sm text-text-muted">{opt.detail}</span>
											{/if}
										</div>
										<Button
											variant={isRecommended ? 'primary' : 'secondary'}
											size="sm"
											onclick={() => void runOption(fmt.id, opt.id)}
											disabled={benchmarking}
										>
											{benchmarking && currentKey?.startsWith(`${opt.id}@`) ? 'Running…' : 'Run'}
										</Button>
									</div>

									{#if rs.length > 0}
										<div class="flex flex-wrap gap-2">
											{#each rs as { threads, r } (threads)}
												<div
													class={`flex items-center gap-2 border px-2 py-1 text-sm ${r.error ? 'border-danger bg-danger/10 text-danger' : fpsClass(r.fps)}`}
												>
													{#if threadCountsFor(opt.id).length > 1}
														<span class="text-xs opacity-70">{threads}t</span>
													{/if}
													{#if r.error}
														<span class="font-medium">failed</span>
													{:else}
														<span class="font-mono font-medium">{r.fps.toFixed(1)} fps</span>
														<span class="font-mono text-xs opacity-70"
															>{r.mean_ms.toFixed(1)} ms</span
														>
													{/if}
												</div>
											{/each}
										</div>
									{/if}
									{#if rs.some((x) => x.r.error)}
										{@const failed = rs.find((x) => x.r.error)}
										<span class="text-sm break-words text-danger">{failed?.r.error}</span>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</Modal>
