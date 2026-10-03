<script lang="ts">
	import { onMount } from 'svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Button from '$lib/components/ui/Button.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';

	type Option = {
		id: string;
		label: string;
		available: boolean;
		reason?: string | null;
		rank: number;
		detail?: string;
	};

	type Format = {
		id: string;
		label: string;
		extensions: string[];
		description: string;
		options: Option[];
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	type InstalledModel = {
		local_id: string;
		name?: string | null;
		model_id?: string | null;
		variant_runtime?: string | null;
	};

	type BenchResult = {
		fps: number;
		mean_ms: number;
		p50_ms: number;
		p90_ms: number;
		threads: number;
		local_id: string;
		model_label: string;
		error?: string;
	};

	let formats = $state<Format[]>([]);
	let error = $state<string | null>(null);
	let loading = $state(true);
	let showAll = $state(false);

	let preferences = $state<Record<string, string>>({});
	let cpuCores = $state<number>(1);

	let installedModels = $state<InstalledModel[]>([]);
	let selectedModel = $state<string | null>(null);
	let benchmarking = $state(false);
	let benchmarkCurrent = $state<string | null>(null);
	// Results keyed by `${option_id}@${threads}` → BenchResult.
	let results = $state<Record<string, BenchResult>>({});

	const BENCH_ONLY_OPTIONS = new Set([
		'onnx-cpu',
		'onnx-coreml',
		'onnx-cuda',
		'onnx-dml',
		'ncnn-cpu',
		'ncnn-vulkan',
		'rknn-npu-auto',
		'rknn-npu-core0',
		'rknn-npu-core1',
		'rknn-npu-core2'
	]);

	// Map the installed model's `variant_runtime` (from Hive) to the format
	// ids we use in the runtimes endpoint. A model with runtime "onnx" can't
	// be benchmarked as NCNN and vice versa — we mark those as "format not
	// installed" instead of attempting the benchmark and showing "failed".
	function formatIdsFromVariant(variant: string | null | undefined): Set<string> {
		const v = (variant ?? '').toLowerCase();
		if (v.includes('onnx')) return new Set(['onnx']);
		if (v.includes('ncnn')) return new Set(['ncnn']);
		if (v.includes('rknn')) return new Set(['rknn']);
		if (v.includes('hef') || v.includes('hailo')) return new Set(['hailo']);
		if (v.includes('pt') || v.includes('torch')) return new Set(['pytorch']);
		return new Set();
	}

	let selectedModelFormats = $derived.by<Set<string>>(() => {
		const m = installedModels.find((x) => x.local_id === selectedModel);
		return formatIdsFromVariant(m?.variant_runtime ?? null);
	});

	function isRunnable(opt: Option, fmtId: string): boolean {
		if (!opt.available) return false;
		if (!BENCH_ONLY_OPTIONS.has(opt.id)) return false;
		if (selectedModelFormats.size === 0) return true;
		return selectedModelFormats.has(fmtId);
	}

	let visibleFormats = $derived.by<Format[]>(() => {
		if (showAll) return formats;
		return formats
			.map((fmt) => ({ ...fmt, options: fmt.options.filter((o) => o.available) }))
			.filter((fmt) => fmt.options.length > 0);
	});

	let hiddenFormatsCount = $derived.by<number>(() => {
		if (showAll) return 0;
		const hiddenFormats = formats.filter((f) => f.options.every((o) => !o.available)).length;
		const hiddenOptions = formats
			.flatMap((f) => f.options.filter((o) => !o.available && f.options.some((x) => x.available))).length;
		return hiddenFormats + hiddenOptions;
	});

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${effectiveBase()}/api/runtimes/formats`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const payload = await res.json();
			formats = Array.isArray(payload?.formats) ? payload.formats : [];
		} catch (e: any) {
			error = e?.message ?? 'Failed to load runtimes';
		} finally {
			loading = false;
		}
	}

	async function loadCapabilities() {
		try {
			const res = await fetch(`${effectiveBase()}/api/runtimes/capabilities`);
			if (!res.ok) return;
			const payload = await res.json();
			const cores = Number(payload?.cpu?.cores ?? 0);
			if (cores > 0) cpuCores = cores;
		} catch {
			// ignore
		}
	}

	async function loadPreferences() {
		try {
			const res = await fetch(`${effectiveBase()}/api/runtimes/preferences`);
			if (!res.ok) return;
			const payload = await res.json();
			preferences = (payload?.preferences ?? {}) as Record<string, string>;
		} catch {
			// ignore
		}
	}

	async function selectPreference(formatId: string, optionId: string) {
		// Optimistic update so the radio responds instantly.
		preferences = { ...preferences, [formatId]: optionId };
		try {
			const res = await fetch(`${effectiveBase()}/api/runtimes/preferences`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ format_id: formatId, option_id: optionId })
			});
			if (!res.ok) return;
			const payload = await res.json();
			preferences = (payload?.preferences ?? preferences) as Record<string, string>;
		} catch {
			// swallow — optimistic state already applied
		}
	}

	async function loadInstalled() {
		try {
			const res = await fetch(`${effectiveBase()}/api/hive/models/installed`);
			if (!res.ok) return;
			const payload = await res.json();
			const items: InstalledModel[] = Array.isArray(payload?.items) ? payload.items : [];
			installedModels = items;
			if (selectedModel === null && items.length > 0) {
				selectedModel = items[0].local_id;
			}
		} catch {
			// ignore
		}
	}

	function modelLabel(m: InstalledModel): string {
		const name = m.name ?? m.local_id;
		const runtime = m.variant_runtime ? ` · ${m.variant_runtime}` : '';
		return `${name}${runtime}`;
	}

	function resultKey(optionId: string, threads: number, localId: string): string {
		return `${optionId}@${threads}@${localId}`;
	}

	function modelLabelFor(localId: string): string {
		const m = installedModels.find((x) => x.local_id === localId);
		return m?.name ?? localId;
	}

	async function runBenchmark(optionId: string, threads: number) {
		if (!selectedModel) return;
		const localId = selectedModel;
		const key = resultKey(optionId, threads, localId);
		const modelLabel = modelLabelFor(localId);
		benchmarkCurrent = key;
		try {
			const res = await fetch(`${effectiveBase()}/api/runtimes/benchmark`, {
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
				const text = await res.text();
				results = {
					...results,
					[key]: {
						fps: 0,
						mean_ms: 0,
						p50_ms: 0,
						p90_ms: 0,
						threads,
						local_id: localId,
						model_label: modelLabel,
						error: text.slice(0, 160)
					}
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
					threads: data.threads ?? threads,
					local_id: localId,
					model_label: modelLabel
				}
			};
		} catch (e: any) {
			results = {
				...results,
				[key]: {
					fps: 0,
					mean_ms: 0,
					p50_ms: 0,
					p90_ms: 0,
					threads,
					local_id: localId,
					model_label: modelLabel,
					error: e?.message ?? 'failed'
				}
			};
		} finally {
			if (benchmarkCurrent === key) benchmarkCurrent = null;
		}
	}

	async function runAll() {
		if (!selectedModel || benchmarking) return;
		benchmarking = true;
		try {
			// Flatten the matrix of (option, threads) to benchmark — only
			// supported + available backends on this machine.
			const queue: { optionId: string; threads: number }[] = [];
			for (const fmt of formats) {
				for (const opt of fmt.options) {
					if (!isRunnable(opt, fmt.id)) continue;
					for (const t of threadCountsFor(opt.id)) {
						queue.push({ optionId: opt.id, threads: t });
					}
				}
			}
			for (const item of queue) {
				await runBenchmark(item.optionId, item.threads);
			}
		} finally {
			benchmarking = false;
			benchmarkCurrent = null;
		}
	}

	function fpsClass(fps: number): string {
		// Thresholds reflect how many 30-fps video streams the host can keep
		// up with: 90 fps → 3 streams, 60 fps → 2 streams, below → deficit.
		if (fps >= 90) return 'bg-success-soft text-success-ink';
		if (fps >= 60) return 'bg-warning-soft text-warning-ink';
		return 'bg-danger-soft text-danger-ink';
	}

	function threadCountsFor(optionId: string): number[] {
		// Thread sweep — only matters for CPU-bound paths. GPU/accelerator
		// providers (CoreML, CUDA, Vulkan, Hailo) do their own scheduling so
		// we just run once with 1 "thread" and let them take over. Half-max
		// approximates the P-core count on Apple Silicon and catches the
		// real sweet spot before the E-cores drag the result down.
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

	function resultsFor(opt: Option): BenchResult[] {
		const keys = Object.keys(results).filter((k) => k.startsWith(`${opt.id}@`));
		return keys
			.map((k) => results[k])
			.sort((a, b) => {
				const byModel = a.model_label.localeCompare(b.model_label);
				if (byModel !== 0) return byModel;
				return a.threads - b.threads;
			});
	}

	onMount(() => {
		void load();
		void loadInstalled();
		void loadPreferences();
		void loadCapabilities();
	});

	function rankLabel(rank: number): string {
		if (rank <= 1) return 'Fastest';
		if (rank === 2) return 'Fast';
		if (rank === 3) return 'OK';
		if (rank === 4) return 'Baseline';
		return 'Slow';
	}

	function rankColor(rank: number, available: boolean): string {
		if (!available) return 'bg-ink-faint';
		if (rank <= 1) return 'bg-success';
		if (rank === 2) return 'bg-success';
		if (rank === 3) return 'bg-primary';
		if (rank === 4) return 'bg-primary';
		return 'bg-warning';
	}

	function formatSupportLine(fmt: Format): string {
		const available = fmt.options.filter((o) => o.available).length;
		const total = fmt.options.length;
		return `${available} of ${total} backend${total === 1 ? '' : 's'} available`;
	}

	function formatUnsupported(fmt: Format): boolean {
		return fmt.options.every((o) => !o.available);
	}
</script>

<div class="flex flex-col gap-4">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<p class="text-sm text-ink-muted">
			{#if !loading && !error}
				{#if showAll}
					Everything, including the backends this machine can't use.
				{:else if hiddenFormatsCount > 0}
					Only the backends this machine supports; {hiddenFormatsCount} hidden.
				{:else}
					Every backend is supported on this machine.
				{/if}
			{/if}
		</p>
		<div class="flex items-center gap-3">
			<Checkbox bind:checked={showAll}>Show the unsupported ones</Checkbox>
			<Button variant="ghost" size="sm" icon={RefreshCw} label="Scan the runtimes again" onclick={load} />
		</div>
	</div>

	{#if loading}
		<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Finding the runtimes</div>
	{:else if error}
		<Alert tone="danger">{error}</Alert>
	{:else if visibleFormats.length === 0}
		<p class="text-sm text-ink-muted">
			{showAll
				? 'No runtimes reported.'
				: "This machine supports none of them. Show the unsupported ones to see what could work elsewhere."}
		</p>
	{:else}
		<div class="grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(280px, 480px));">
			{#each visibleFormats as fmt (fmt.id)}
				<section class="overflow-hidden rounded-control bg-well" class:opacity-60={formatUnsupported(fmt)}>
					<header class="flex flex-col gap-1 px-3 py-2.5">
						<div class="flex items-center justify-between gap-2">
							<h3 class="text-base font-semibold text-ink">{fmt.label}</h3>
							<span class="font-mono text-xs text-ink-muted">{fmt.extensions.join(' / ')}</span>
						</div>
						<p class="text-sm text-ink-muted">{fmt.description}</p>
						<p class="text-sm text-ink-muted">{formatSupportLine(fmt)}</p>
					</header>
					<div class="divide-y divide-line border-t border-line">
						{#each fmt.options as opt (opt.id)}
							<label class="flex items-start gap-3 px-3 py-2.5" class:opacity-50={!opt.available}>
								{#if opt.available}
									<span class="relative mt-0.5 inline-flex size-4 shrink-0">
										<input
											type="radio"
											name="runtime-pref-{fmt.id}"
											value={opt.id}
											checked={preferences[fmt.id] === opt.id}
											onchange={() => void selectPreference(fmt.id, opt.id)}
											aria-label="Use {opt.label} for {fmt.label}"
											class="peer size-4 cursor-pointer appearance-none rounded-radio border border-line-strong bg-field transition-colors checked:border-primary hover:border-ink-faint"
										/>
										<span
											class="pointer-events-none absolute inset-1 rounded-radio bg-primary opacity-0 peer-checked:opacity-100"
										></span>
									</span>
								{:else}
									<span
										class="mt-1.5 inline-flex size-2 shrink-0 rounded-full {rankColor(opt.rank, opt.available)}"
										aria-hidden="true"
									></span>
								{/if}
								<span class="flex min-w-0 flex-1 flex-col gap-1">
									<span class="flex items-center justify-between gap-2">
										<span class="text-sm font-medium text-ink">{opt.label}</span>
										{#if opt.available}<Badge>{rankLabel(opt.rank)}</Badge>{/if}
									</span>
									<span class="text-sm text-ink-muted">
										{opt.available ? opt.detail || 'Ready' : opt.reason || 'Unavailable'}
									</span>
									{#if opt.available && (isRunnable(opt, fmt.id) || resultsFor(opt).length > 0)}
										{#each resultsFor(opt) as r (`${r.local_id}@${r.threads}`)}
											<span
												class="flex items-center justify-between gap-2 rounded-control px-2 py-1 text-sm {r.error
													? 'bg-danger-soft text-danger-ink'
													: fpsClass(r.fps)}"
											>
												<span class="flex min-w-0 flex-col">
													<span class="truncate" title={r.model_label}>{r.model_label}</span>
													<span class="opacity-80">{r.threads} {r.threads === 1 ? 'thread' : 'threads'}</span>
												</span>
												{#if r.error}
													<span title={r.error}>Failed</span>
												{:else}
													<span class="num font-medium">
														{r.fps.toFixed(1)} fps
														<span class="opacity-70">· {r.mean_ms.toFixed(1)} ms</span>
													</span>
												{/if}
											</span>
										{/each}
										{#if benchmarking && selectedModel}
											{#each threadCountsFor(opt.id) as threadN (threadN)}
												{#if benchmarkCurrent === resultKey(opt.id, threadN, selectedModel)}
													<span class="flex items-center gap-1.5 text-sm text-primary-ink">
														<Spinner size={12} /> Running {threadN}
														{threadN === 1 ? 'thread' : 'threads'}
													</span>
												{/if}
											{/each}
										{/if}
									{/if}
								</span>
							</label>
						{/each}
					</div>
				</section>
			{/each}
		</div>
	{/if}

	{#if !loading && !error && formats.length > 0}
		<div class="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-4">
			<span class="text-sm text-ink-muted">Benchmark with</span>
			<div class="w-64">
				<Select
					label="Model to benchmark"
					value={selectedModel ?? undefined}
					onchange={(id) => (selectedModel = id)}
					disabled={benchmarking || installedModels.length === 0}
					placeholder="No installed models"
					options={installedModels.map((m) => ({ value: m.local_id, label: modelLabel(m) }))}
				/>
			</div>
			<Button
				variant="primary"
				loading={benchmarking}
				disabled={!selectedModel}
				onclick={runAll}
			>
				Benchmark them all
			</Button>
		</div>
	{/if}
</div>
