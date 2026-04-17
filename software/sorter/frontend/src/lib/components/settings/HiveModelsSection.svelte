<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl } from '$lib/backend';
	import {
		Download,
		RefreshCw,
		Trash2,
		Search,
		CheckCircle2,
		XCircle,
		Loader2,
		Clock
	} from 'lucide-svelte';

	type HiveTarget = { id: string; name: string; url: string };
	type ModelSummary = {
		id: string;
		slug: string;
		version: number;
		name: string;
		description: string | null;
		model_family: string;
		scopes: string[] | null;
		is_public: boolean;
		published_at: string;
		updated_at: string;
		variant_runtimes: string[];
		installed: boolean;
	};
	type ModelVariant = {
		id: string;
		runtime: string;
		file_name: string;
		file_size: number;
		sha256: string;
		format_meta: Record<string, unknown> | null;
		uploaded_at: string;
	};
	type ModelDetail = ModelSummary & {
		training_metadata: Record<string, unknown> | null;
		variants: ModelVariant[];
		recommended_runtime: string | null;
	};
	type Installed = {
		local_id: string;
		target_id: string;
		model_id: string;
		variant_runtime: string;
		sha256: string;
		name: string;
		model_family: string;
		size_bytes: number;
		downloaded_at: string;
		path: string;
	};
	type Job = {
		job_id: string;
		status: 'queued' | 'downloading' | 'done' | 'failed';
		target_id: string;
		model_id: string;
		variant_runtime: string;
		variant_id: string;
		file_name: string;
		total_bytes: number;
		progress_bytes: number;
		error: string | null;
		created_at: string;
		updated_at: string;
	};

	type ModelsPage = {
		items: ModelSummary[];
		total: number;
		page: number;
		page_size: number;
		pages: number;
	};

	const RUNTIME_OPTIONS = ['', 'onnx', 'ncnn', 'hailo', 'pytorch'] as const;
	const PAGE_SIZE = 20;

	let targets = $state<HiveTarget[]>([]);
	let selectedTargetId = $state<string | null>(null);
	let targetsLoading = $state(true);
	let targetsError = $state<string | null>(null);
	let targetsMissing = $state(false);

	let tab = $state<'available' | 'installed' | 'downloads'>('available');

	let query = $state('');
	let scopeFilter = $state('');
	let runtimeFilter = $state('');
	let familyFilter = $state('');

	let page = $state(1);
	let models = $state<ModelSummary[]>([]);
	let modelsTotal = $state(0);
	let modelsPages = $state(1);
	let loadingModels = $state(false);
	let modelsError = $state<string | null>(null);

	let installed = $state<Installed[]>([]);
	let loadingInstalled = $state(false);
	let installedError = $state<string | null>(null);

	let jobs = $state<Job[]>([]);
	let jobsError = $state<string | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let downloadingModelId = $state<string | null>(null);
	let deletingLocalId = $state<string | null>(null);
	let actionError = $state<string | null>(null);
	let actionStatus = $state<string | null>(null);

	const detailCache = new Map<string, ModelDetail>();

	const availableRuntimes = ['onnx', 'ncnn', 'hailo', 'pytorch'];

	const hasActiveJob = $derived(
		jobs.some((job) => job.status === 'queued' || job.status === 'downloading')
	);

	const activeJobModelIds = $derived(
		new Set(
			jobs
				.filter((job) => job.status === 'queued' || job.status === 'downloading')
				.map((job) => job.model_id)
		)
	);

	const sortedJobs = $derived(
		[...jobs].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
	);

	function formatSize(bytes: number | null | undefined): string {
		if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '—';
		if (bytes < 1024) return `${bytes} B`;
		const units = ['KB', 'MB', 'GB', 'TB'];
		let value = bytes / 1024;
		let idx = 0;
		while (value >= 1024 && idx < units.length - 1) {
			value /= 1024;
			idx += 1;
		}
		return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${units[idx]}`;
	}

	function formatDate(iso: string | null | undefined): string {
		if (!iso) return '—';
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		return d.toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: '2-digit'
		});
	}

	function progressPct(job: Job): number {
		if (!Number.isFinite(job.total_bytes) || job.total_bytes <= 0) {
			if (job.status === 'done') return 100;
			return 0;
		}
		const pct = (job.progress_bytes / job.total_bytes) * 100;
		if (!Number.isFinite(pct)) return 0;
		return Math.max(0, Math.min(100, pct));
	}

	async function loadTargets() {
		targetsLoading = true;
		targetsError = null;
		targetsMissing = false;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/hive/targets`);
			if (res.status === 400) {
				targetsMissing = true;
				targets = [];
				selectedTargetId = null;
				return;
			}
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = (await res.json()) as HiveTarget[];
			targets = Array.isArray(data) ? data : [];
			if (targets.length === 0) {
				targetsMissing = true;
				selectedTargetId = null;
			} else if (!selectedTargetId || !targets.some((t) => t.id === selectedTargetId)) {
				selectedTargetId = targets[0].id;
			}
		} catch (e: any) {
			targetsError = e?.message ?? 'Failed to load Hive targets.';
			targets = [];
			selectedTargetId = null;
		} finally {
			targetsLoading = false;
		}
	}

	async function loadModels() {
		if (!selectedTargetId) {
			models = [];
			modelsTotal = 0;
			modelsPages = 1;
			return;
		}
		loadingModels = true;
		modelsError = null;
		try {
			const params = new URLSearchParams();
			params.set('target_id', selectedTargetId);
			if (query.trim()) params.set('q', query.trim());
			if (scopeFilter.trim()) params.set('scope', scopeFilter.trim());
			if (runtimeFilter) params.set('runtime', runtimeFilter);
			if (familyFilter.trim()) params.set('family', familyFilter.trim());
			params.set('page', String(page));
			params.set('page_size', String(PAGE_SIZE));
			const res = await fetch(`${backendHttpBaseUrl}/api/hive/models?${params.toString()}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const raw = await res.json();
			let parsed: ModelsPage;
			if (Array.isArray(raw)) {
				parsed = {
					items: raw as ModelSummary[],
					total: raw.length,
					page: 1,
					page_size: raw.length,
					pages: 1
				};
			} else {
				parsed = {
					items: Array.isArray(raw?.items) ? (raw.items as ModelSummary[]) : [],
					total: Number.isFinite(raw?.total) ? Number(raw.total) : 0,
					page: Number.isFinite(raw?.page) ? Number(raw.page) : 1,
					page_size: Number.isFinite(raw?.page_size) ? Number(raw.page_size) : PAGE_SIZE,
					pages: Number.isFinite(raw?.pages) ? Number(raw.pages) : 1
				};
			}
			models = parsed.items;
			modelsTotal = parsed.total;
			modelsPages = Math.max(1, parsed.pages);
		} catch (e: any) {
			modelsError = e?.message ?? 'Failed to load models.';
			models = [];
			modelsTotal = 0;
			modelsPages = 1;
		} finally {
			loadingModels = false;
		}
	}

	async function loadInstalled() {
		loadingInstalled = true;
		installedError = null;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/hive/models/installed`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			installed = Array.isArray(data) ? (data as Installed[]) : [];
		} catch (e: any) {
			installedError = e?.message ?? 'Failed to load installed models.';
			installed = [];
		} finally {
			loadingInstalled = false;
		}
	}

	async function loadDownloads() {
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/hive/downloads`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			const next: Job[] = Array.isArray(data?.jobs) ? (data.jobs as Job[]) : [];

			const prevActive = new Set(
				jobs
					.filter((j) => j.status === 'queued' || j.status === 'downloading')
					.map((j) => j.job_id)
			);
			let anyFinished = false;
			for (const job of next) {
				if (
					prevActive.has(job.job_id) &&
					(job.status === 'done' || job.status === 'failed')
				) {
					anyFinished = true;
					break;
				}
			}

			jobs = next;
			jobsError = null;

			if (anyFinished) {
				void loadInstalled();
				if (tab === 'available') {
					void loadModels();
				}
			}
		} catch (e: any) {
			jobsError = e?.message ?? 'Failed to load downloads.';
		}
	}

	function resetFilters() {
		query = '';
		scopeFilter = '';
		runtimeFilter = '';
		familyFilter = '';
		page = 1;
	}

	async function ensureDetail(modelId: string): Promise<ModelDetail | null> {
		if (!selectedTargetId) return null;
		const cached = detailCache.get(modelId);
		if (cached) return cached;
		try {
			const params = new URLSearchParams();
			params.set('target_id', selectedTargetId);
			const res = await fetch(
				`${backendHttpBaseUrl}/api/hive/models/${encodeURIComponent(modelId)}?${params.toString()}`
			);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = (await res.json()) as ModelDetail;
			detailCache.set(modelId, data);
			return data;
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to load model details.';
			return null;
		}
	}

	async function handleDownload(model: ModelSummary, runtimeOverride?: string) {
		if (!selectedTargetId) return;
		actionError = null;
		actionStatus = null;
		downloadingModelId = model.id;
		try {
			let variantRuntime: string | null = runtimeOverride ?? null;
			if (!variantRuntime) {
				const detail = await ensureDetail(model.id);
				variantRuntime = detail?.recommended_runtime ?? null;
			}
			const params = new URLSearchParams();
			params.set('target_id', selectedTargetId);
			if (variantRuntime) params.set('variant_runtime', variantRuntime);
			const res = await fetch(
				`${backendHttpBaseUrl}/api/hive/models/${encodeURIComponent(model.id)}/download?${params.toString()}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				let body = '';
				try {
					body = await res.text();
				} catch {
					body = '';
				}
				throw new Error(body || `HTTP ${res.status}`);
			}
			actionStatus = `Queued download for ${model.name}.`;
			await loadDownloads();
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to enqueue download.';
		} finally {
			downloadingModelId = null;
		}
	}

	async function handleDelete(entry: Installed) {
		if (!confirm(`Remove the installed model "${entry.name}" from this sorter?`)) return;
		actionError = null;
		actionStatus = null;
		deletingLocalId = entry.local_id;
		try {
			const res = await fetch(
				`${backendHttpBaseUrl}/api/hive/models/installed/${encodeURIComponent(entry.local_id)}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) {
				let body = '';
				try {
					body = await res.text();
				} catch {
					body = '';
				}
				throw new Error(body || `HTTP ${res.status}`);
			}
			actionStatus = `Removed ${entry.name}.`;
			await loadInstalled();
			if (tab === 'available') {
				await loadModels();
			}
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to delete model.';
		} finally {
			deletingLocalId = null;
		}
	}

	function stopPolling() {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	function startPolling() {
		if (pollTimer !== null) return;
		pollTimer = setInterval(() => {
			void loadDownloads();
		}, 2000);
	}

	$effect(() => {
		if (tab === 'available' && selectedTargetId) {
			// Track dependencies so the effect re-runs when they change.
			void query;
			void scopeFilter;
			void runtimeFilter;
			void familyFilter;
			void page;
			void loadModels();
		}
	});

	$effect(() => {
		if (tab === 'installed') {
			void loadInstalled();
		}
	});

	$effect(() => {
		const shouldPoll = tab === 'downloads' || hasActiveJob;
		if (shouldPoll) {
			startPolling();
		} else {
			stopPolling();
		}
		return () => {
			stopPolling();
		};
	});

	onMount(() => {
		void (async () => {
			await loadTargets();
			await Promise.all([loadInstalled(), loadDownloads()]);
		})();
		return () => {
			stopPolling();
		};
	});

	function setTab(next: 'available' | 'installed' | 'downloads') {
		tab = next;
		if (next === 'downloads') {
			void loadDownloads();
		}
	}

	function onFilterChange() {
		page = 1;
	}

	function prevPage() {
		if (page > 1) page -= 1;
	}

	function nextPage() {
		if (page < modelsPages) page += 1;
	}

	function statusLabel(status: Job['status']): string {
		switch (status) {
			case 'queued':
				return 'Queued';
			case 'downloading':
				return 'Downloading';
			case 'done':
				return 'Done';
			case 'failed':
				return 'Failed';
			default:
				return status;
		}
	}

	function statusToneClass(status: Job['status']): string {
		switch (status) {
			case 'done':
				return 'text-success dark:text-emerald-400';
			case 'failed':
				return 'text-danger';
			case 'downloading':
				return 'text-primary';
			default:
				return 'text-text-muted';
		}
	}

	function targetName(id: string): string {
		return targets.find((t) => t.id === id)?.name ?? id;
	}

	function shortSha(sha: string | null | undefined): string {
		if (!sha) return '—';
		return `${sha.slice(0, 12)}…`;
	}
</script>

<div class="grid gap-4">
	{#if targetsLoading}
		<div class="text-sm text-text-muted">Loading Hive targets…</div>
	{:else if targetsMissing}
		<div class="border border-border bg-surface px-3 py-3 text-sm text-text-muted">
			Configure a Hive target in the Hive card above to browse and download detection models.
		</div>
	{:else if targetsError}
		<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:text-red-400">
			{targetsError}
		</div>
	{:else}
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="flex items-center gap-2">
				{#if targets.length > 1}
					<label class="text-xs text-text-muted" for="hive-target-select">Target</label>
					<select
						id="hive-target-select"
						bind:value={selectedTargetId}
						class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
					>
						{#each targets as t (t.id)}
							<option value={t.id}>{t.name}</option>
						{/each}
					</select>
				{:else if targets.length === 1}
					<span class="text-xs text-text-muted">Target: {targets[0].name}</span>
				{/if}
			</div>
			<button
				type="button"
				onclick={() => {
					if (tab === 'available') void loadModels();
					if (tab === 'installed') void loadInstalled();
					if (tab === 'downloads') void loadDownloads();
				}}
				class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface"
				title="Refresh"
			>
				<RefreshCw size={12} />
				Refresh
			</button>
		</div>

		<div class="flex items-center gap-4 border-b border-border">
			<button
				type="button"
				onclick={() => setTab('available')}
				class={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${tab === 'available' ? 'border-primary text-text' : 'border-transparent text-text-muted hover:text-text'}`}
			>
				Available
			</button>
			<button
				type="button"
				onclick={() => setTab('installed')}
				class={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${tab === 'installed' ? 'border-primary text-text' : 'border-transparent text-text-muted hover:text-text'}`}
			>
				Installed
				{#if installed.length > 0}
					<span class="ml-1 text-xs text-text-muted">({installed.length})</span>
				{/if}
			</button>
			<button
				type="button"
				onclick={() => setTab('downloads')}
				class={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${tab === 'downloads' ? 'border-primary text-text' : 'border-transparent text-text-muted hover:text-text'}`}
			>
				Downloads
				{#if hasActiveJob}
					<span class="ml-1 text-xs text-primary">(active)</span>
				{/if}
			</button>
		</div>

		{#if actionError}
			<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:text-red-400">
				{actionError}
			</div>
		{/if}
		{#if actionStatus}
			<div class="text-sm text-text-muted">{actionStatus}</div>
		{/if}

		{#if tab === 'available'}
			<div class="grid gap-3 border border-border bg-surface px-3 py-3">
				<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
					<div class="relative">
						<Search
							size={12}
							class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
						/>
						<input
							bind:value={query}
							oninput={onFilterChange}
							type="text"
							placeholder="Search name or slug"
							class="w-full border border-border bg-bg py-1.5 pl-7 pr-2 text-sm text-text"
						/>
					</div>
					<input
						bind:value={scopeFilter}
						oninput={onFilterChange}
						type="text"
						placeholder="Scope (e.g. brick, minifig)"
						class="w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
					<select
						bind:value={runtimeFilter}
						onchange={onFilterChange}
						class="w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					>
						{#each RUNTIME_OPTIONS as opt}
							<option value={opt}>{opt === '' ? 'Any runtime' : opt}</option>
						{/each}
					</select>
					<input
						bind:value={familyFilter}
						oninput={onFilterChange}
						type="text"
						placeholder="Model family"
						class="w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
				</div>
				<div class="flex items-center justify-between gap-2 text-xs text-text-muted">
					<span>
						{#if loadingModels}
							Loading models…
						{:else}
							{modelsTotal} model{modelsTotal === 1 ? '' : 's'} — page {page} of {modelsPages}
						{/if}
					</span>
					<button
						type="button"
						onclick={resetFilters}
						class="border border-border bg-bg px-2 py-1 text-xs text-text transition-colors hover:bg-surface"
					>
						Reset filters
					</button>
				</div>
			</div>

			{#if modelsError}
				<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:text-red-400">
					{modelsError}
				</div>
			{/if}

			{#if !loadingModels && models.length === 0 && !modelsError}
				<div class="border border-border bg-surface px-3 py-3 text-sm text-text-muted">
					No models found.
				</div>
			{/if}

			<div class="grid gap-3">
				{#each models as model (model.id)}
					{@const detail = detailCache.get(model.id) ?? null}
					{@const recommended = detail?.recommended_runtime ?? null}
					{@const jobActive = activeJobModelIds.has(model.id)}
					<div class="border border-border bg-surface px-3 py-3">
						<div class="flex flex-wrap items-start justify-between gap-3">
							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-2">
									<span class="text-sm font-medium text-text">{model.name}</span>
									{#if model.installed}
										<span class="inline-flex items-center gap-1 border border-success bg-success/10 px-1.5 py-0.5 text-xs font-medium text-success dark:border-emerald-400 dark:text-emerald-300">
											<CheckCircle2 size={10} />
											Installed
										</span>
									{/if}
								</div>
								<div class="mt-0.5 text-xs text-text-muted">
									<span class="font-mono">{model.slug}</span>
									· v{model.version}
									· {model.model_family}
									· published {formatDate(model.published_at)}
								</div>
								{#if model.description}
									<div class="mt-2 text-sm text-text-muted">{model.description}</div>
								{/if}
								{#if (model.scopes ?? []).length > 0}
									<div class="mt-2 flex flex-wrap gap-1">
										{#each model.scopes ?? [] as scope}
											<span class="border border-border bg-bg px-1.5 py-0.5 text-xs text-text-muted">
												{scope}
											</span>
										{/each}
									</div>
								{/if}
								{#if model.variant_runtimes.length > 0}
									<div class="mt-2 flex flex-wrap gap-1">
										{#each model.variant_runtimes as runtime}
											{@const isRecommended = recommended === runtime}
											<span
												class={`border px-1.5 py-0.5 text-xs ${isRecommended ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-bg text-text-muted'}`}
											>
												{runtime}{isRecommended ? ' · recommended' : ''}
											</span>
										{/each}
									</div>
								{/if}
							</div>

							<div class="flex flex-col items-end gap-2">
								<button
									type="button"
									onclick={() => void handleDownload(model)}
									disabled={jobActive || downloadingModelId === model.id || !selectedTargetId}
									class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
								>
									<Download size={12} />
									{jobActive
										? 'In progress'
										: downloadingModelId === model.id
											? 'Queueing…'
											: model.installed
												? 'Download again'
												: 'Download'}
								</button>
								{#if availableRuntimes.length > 1 && model.variant_runtimes.length > 0}
									<details class="text-right">
										<summary class="cursor-pointer text-xs text-text-muted hover:text-text">
											Override runtime
										</summary>
										<div class="mt-1 flex flex-wrap justify-end gap-1">
											{#each model.variant_runtimes as runtime}
												<button
													type="button"
													onclick={() => void handleDownload(model, runtime)}
													disabled={jobActive || downloadingModelId === model.id}
													class="border border-border bg-bg px-2 py-0.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
												>
													{runtime}
												</button>
											{/each}
										</div>
									</details>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>

			{#if modelsPages > 1}
				<div class="flex items-center justify-end gap-2 text-xs">
					<button
						type="button"
						onclick={prevPage}
						disabled={page <= 1}
						class="border border-border bg-bg px-2 py-1 text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						Previous
					</button>
					<span class="text-text-muted">Page {page} of {modelsPages}</span>
					<button
						type="button"
						onclick={nextPage}
						disabled={page >= modelsPages}
						class="border border-border bg-bg px-2 py-1 text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						Next
					</button>
				</div>
			{/if}
		{:else if tab === 'installed'}
			{#if installedError}
				<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:text-red-400">
					{installedError}
				</div>
			{/if}
			{#if loadingInstalled}
				<div class="text-sm text-text-muted">Loading installed models…</div>
			{:else if installed.length === 0}
				<div class="border border-border bg-surface px-3 py-3 text-sm text-text-muted">
					No models installed yet. Download one from the Available tab.
				</div>
			{:else}
				<div class="grid gap-3">
					{#each installed as entry (entry.local_id)}
						<div class="border border-border bg-surface px-3 py-3">
							<div class="flex flex-wrap items-start justify-between gap-3">
								<div class="min-w-0">
									<div class="flex flex-wrap items-center gap-2">
										<span class="text-sm font-medium text-text">{entry.name}</span>
										<span class="border border-primary bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
											{entry.variant_runtime}
										</span>
										<span class="border border-border bg-bg px-1.5 py-0.5 text-xs text-text-muted">
											{entry.model_family}
										</span>
									</div>
									<div class="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
										<span class="text-text-muted">SHA-256</span>
										<span class="font-mono text-text">{shortSha(entry.sha256)}</span>
										<span class="text-text-muted">Size</span>
										<span class="text-text">{formatSize(entry.size_bytes)}</span>
										<span class="text-text-muted">Downloaded</span>
										<span class="text-text">{formatDate(entry.downloaded_at)}</span>
										<span class="text-text-muted">Target</span>
										<span class="text-text">{targetName(entry.target_id)}</span>
										<span class="text-text-muted">Path</span>
										<span class="truncate font-mono text-text" title={entry.path}>{entry.path}</span>
									</div>
								</div>
								<button
									type="button"
									onclick={() => void handleDelete(entry)}
									disabled={deletingLocalId === entry.local_id}
									class="inline-flex items-center gap-1.5 border border-danger bg-danger px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-danger/80 disabled:cursor-not-allowed disabled:opacity-50"
								>
									<Trash2 size={12} />
									{deletingLocalId === entry.local_id ? 'Removing…' : 'Remove'}
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		{:else if tab === 'downloads'}
			{#if jobsError}
				<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:text-red-400">
					{jobsError}
				</div>
			{/if}
			{#if sortedJobs.length === 0}
				<div class="border border-border bg-surface px-3 py-3 text-sm text-text-muted">
					No download jobs yet.
				</div>
			{:else}
				<div class="grid gap-3">
					{#each sortedJobs as job (job.job_id)}
						{@const pct = progressPct(job)}
						<div class="border border-border bg-surface px-3 py-3">
							<div class="flex flex-wrap items-start justify-between gap-3">
								<div class="min-w-0">
									<div class="flex flex-wrap items-center gap-2">
										{#if job.status === 'done'}
											<CheckCircle2 size={12} class="text-success dark:text-emerald-400" />
										{:else if job.status === 'failed'}
											<XCircle size={12} class="text-danger" />
										{:else if job.status === 'downloading'}
											<Loader2 size={12} class="animate-spin text-primary" />
										{:else}
											<Clock size={12} class="text-text-muted" />
										{/if}
										<span class="text-sm font-medium text-text">{job.file_name || job.variant_id}</span>
										<span class={`text-xs ${statusToneClass(job.status)}`}>
											{statusLabel(job.status)}
										</span>
									</div>
									<div class="mt-0.5 text-xs text-text-muted">
										Target {targetName(job.target_id)}
										· runtime {job.variant_runtime}
										· {formatSize(job.progress_bytes)} / {formatSize(job.total_bytes)}
									</div>
								</div>
								<div class="text-xs text-text-muted">
									{formatDate(job.updated_at || job.created_at)}
								</div>
							</div>
							<div class="mt-3 h-1 w-full bg-bg">
								<div
									class={`h-full ${job.status === 'failed' ? 'bg-danger' : 'bg-primary'}`}
									style={`width: ${pct}%`}
								></div>
							</div>
							{#if job.error}
								<div class="mt-2 text-xs text-danger">{job.error}</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	{/if}
</div>
