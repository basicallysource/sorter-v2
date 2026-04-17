<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { RefreshCw } from 'lucide-svelte';

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
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
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
		'ncnn-vulkan'
	]);

	// Map the installed model's `variant_runtime` (from Hive) to the format
	// ids we use in the runtimes endpoint. A model with runtime "onnx" can't
	// be benchmarked as NCNN and vice versa — we mark those as "format not
	// installed" instead of attempting the benchmark and showing "failed".
	function formatIdsFromVariant(variant: string | null | undefined): Set<string> {
		const v = (variant ?? '').toLowerCase();
		if (v.includes('onnx')) return new Set(['onnx']);
		if (v.includes('ncnn')) return new Set(['ncnn']);
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
		if (fps >= 90) return 'border-success bg-success/10 text-success-dark';
		if (fps >= 60) return 'border-warning bg-warning/10 text-warning-dark';
		return 'border-danger bg-danger/10 text-danger-dark';
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
		if (!available) return 'bg-text-muted/50';
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
	<div class="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-2">
		<div class="text-sm text-text-muted">
			{#if !loading && !error}
				{#if showAll}
					Showing everything, including backends not usable on this machine.
				{:else if hiddenFormatsCount > 0}
					Showing only supported backends. {hiddenFormatsCount} hidden.
				{:else}
					All backends supported on this machine.
				{/if}
			{/if}
		</div>
		<div class="flex items-center gap-3">
			<label class="flex cursor-pointer items-center gap-2 text-sm text-text-muted">
				<input
					type="checkbox"
					bind:checked={showAll}
					class="h-4 w-4 cursor-pointer"
				/>
				<span>Show unsupported</span>
			</label>
			<button
				type="button"
				onclick={load}
				aria-label="Re-scan runtimes"
				title="Re-scan runtimes"
				class="border border-border bg-surface p-1.5 text-text-muted hover:text-text"
			>
				<RefreshCw size={14} />
			</button>
		</div>
	</div>

	{#if loading}
		<div class="text-sm text-text-muted">Detecting runtimes…</div>
	{:else if error}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>
	{:else if visibleFormats.length === 0}
		<div class="text-sm text-text-muted">
			{showAll ? 'No runtimes reported.' : 'No runtimes supported on this machine. Toggle "Show unsupported" to see what could work elsewhere.'}
		</div>
	{:else}
		<div class="grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(280px, 480px));">
			{#each visibleFormats as fmt (fmt.id)}
				<div
					class="flex flex-col border border-border bg-bg"
					class:opacity-60={formatUnsupported(fmt)}
				>
					<div class="flex flex-col gap-1 border-b border-border bg-surface px-3 py-2.5">
						<div class="flex items-center justify-between gap-2">
							<span class="text-base font-semibold text-text">{fmt.label}</span>
							<span class="font-mono text-xs text-text-muted">
								{fmt.extensions.join(' / ')}
							</span>
						</div>
						<span class="text-sm text-text-muted">{fmt.description}</span>
						<span class="mt-0.5 text-xs text-text-muted">{formatSupportLine(fmt)}</span>
					</div>
					<div class="flex flex-col divide-y divide-border">
						{#each fmt.options as opt (opt.id)}
							<div
								class="flex items-start gap-3 px-3 py-2"
								class:opacity-50={!opt.available}
							>
								{#if opt.available}
									<input
										type="radio"
										name={`runtime-pref-${fmt.id}`}
										value={opt.id}
										checked={preferences[fmt.id] === opt.id}
										onchange={() => void selectPreference(fmt.id, opt.id)}
										class="mt-1 h-4 w-4 flex-shrink-0 cursor-pointer accent-primary"
										aria-label={`Use ${opt.label} for ${fmt.label}`}
									/>
								{:else}
									<span
										class={`mt-1 inline-flex h-2 w-2 flex-shrink-0 rounded-full ${rankColor(opt.rank, opt.available)}`}
										aria-hidden="true"
									></span>
								{/if}
								<div class="flex min-w-0 flex-1 flex-col gap-1">
									<div class="flex items-center justify-between gap-2">
										<span class="text-sm font-medium text-text">{opt.label}</span>
										{#if opt.available}
											<span
												class="border border-border px-1.5 py-0.5 text-xs uppercase tracking-wide text-text-muted"
											>
												{rankLabel(opt.rank)}
											</span>
										{/if}
									</div>
									<span class="text-sm text-text-muted">
										{opt.available ? (opt.detail || 'ready') : (opt.reason || 'unavailable')}
									</span>
									{#if opt.available && (isRunnable(opt, fmt.id) || resultsFor(opt).length > 0)}
										{@const rs = resultsFor(opt)}
										{#each rs as r (`${r.local_id}@${r.threads}`)}
											<div
												class={`flex items-center justify-between gap-2 border px-2 py-1 text-sm ${
													r.error ? 'border-danger bg-danger/10 text-danger' : fpsClass(r.fps)
												}`}
											>
												<div class="flex min-w-0 flex-col">
													<span class="truncate text-xs opacity-70" title={r.model_label}>
														{r.model_label}
													</span>
													<span class="opacity-80">
														{r.threads} thread{r.threads === 1 ? '' : 's'}
													</span>
												</div>
												{#if r.error}
													<span title={r.error}>failed</span>
												{:else}
													<span class="font-mono font-medium">
														{r.fps.toFixed(1)} fps
														<span class="opacity-70">· {r.mean_ms.toFixed(1)} ms</span>
													</span>
												{/if}
											</div>
										{/each}
										{#if benchmarking && selectedModel}
											{#each threadCountsFor(opt.id) as threadN (threadN)}
												{#if benchmarkCurrent === resultKey(opt.id, threadN, selectedModel)}
													<div class="flex items-center gap-1.5 text-sm text-primary">
														<div
															class="h-3 w-3 animate-spin border-2 border-current border-t-transparent"
															style="border-radius: 50%;"
														></div>
														<span>running {threadN} thread{threadN === 1 ? '' : 's'}…</span>
													</div>
												{/if}
											{/each}
										{/if}
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}

	{#if !loading && !error && formats.length > 0}
		<div class="flex flex-wrap items-center justify-end gap-3 border-t border-border pt-3">
			<span class="text-sm text-text-muted">Benchmark model:</span>
			<select
				bind:value={selectedModel}
				disabled={benchmarking || installedModels.length === 0}
				class="border border-border bg-surface px-2 py-1 text-sm text-text disabled:opacity-50"
			>
				{#if installedModels.length === 0}
					<option value={null}>No installed models</option>
				{:else}
					{#each installedModels as m (m.local_id)}
						<option value={m.local_id}>{modelLabel(m)}</option>
					{/each}
				{/if}
			</select>
			<button
				type="button"
				onclick={runAll}
				disabled={!selectedModel || benchmarking}
				class="border border-primary/50 bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-50"
			>
				{benchmarking ? 'Benchmarking…' : 'Benchmark all'}
			</button>
		</div>
	{/if}
</div>
