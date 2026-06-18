<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase } from '$lib/backend';
	import { Alert, Button, Tooltip } from '$lib/components/primitives';
	import {
		Download,
		RefreshCw,
		Trash2,
		Search,
		CheckCircle2,
		ChevronDown,
		ChevronRight
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
		target_id?: string | null;
		target_url?: string | null;
		target_name?: string | null;
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
		target_id: string | null;
		model_id: string;
		variant_runtime: string;
		sha256: string;
		name: string;
		model_family: string;
		size_bytes: number;
		downloaded_at: string | null;
		trained_at: string | null;
		path: string;
		bundled?: boolean;
		compatible?: boolean;
		registry_scopes?: string[];
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

	const RUNTIME_OPTIONS = ['', 'onnx', 'ncnn', 'hailo', 'rknn', 'pytorch'] as const;
	const PAGE_SIZE = 20;

	let targets = $state<HiveTarget[]>([]);
	// selectedTargetId is no longer used for browsing — the Browse Hive view
	// aggregates across every configured target and each row carries its own
	// target_id. We still load `targets` to surface the "no Hive configured"
	// empty state and use it as a fallback for resolving the display name of
	// installed models (see targetName()).
	let targetsLoading = $state(true);
	let targetsError = $state<string | null>(null);
	let targetsMissing = $state(false);

	let tab = $state<'available' | 'installed'>('installed');
	let expandedDetailsId = $state<string | null>(null);

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

	type ActiveAssignment = {
		scope: string;
		role: string | null;
		label: string;
		algorithm_id: string | null;
		registry_scope?: string;
		group?: string;
	};
	let activeAssignments = $state<ActiveAssignment[]>([]);

	let jobs = $state<Job[]>([]);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let downloadingModelId = $state<string | null>(null);
	let deletingLocalId = $state<string | null>(null);
	let activatingAlgorithmId = $state<string | null>(null);
	// Tracks which model's activate dropdown is open. Hover alone is unreachable
	// on the CM5 touch tablet, so the panel toggles open on tap.
	let openActivateId = $state<string | null>(null);
	let cleaningUp = $state(false);
	let actionError = $state<string | null>(null);

	const detailCache = new Map<string, ModelDetail>();

	const availableRuntimes = ['onnx', 'ncnn', 'hailo', 'rknn', 'pytorch'];

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

	function formatRelativeAge(iso: string | null | undefined): string | null {
		if (!iso) return null;
		const then = new Date(iso).getTime();
		if (!Number.isFinite(then)) return null;
		const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
		if (seconds < 60) return 'just now';
		const minutes = Math.round(seconds / 60);
		if (minutes < 60) return `${minutes} min ago`;
		const hours = Math.round(minutes / 60);
		if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
		const days = Math.round(hours / 24);
		if (days < 14) return `${days} day${days === 1 ? '' : 's'} ago`;
		const weeks = Math.round(days / 7);
		if (weeks < 9) return `${weeks} week${weeks === 1 ? '' : 's'} ago`;
		const months = Math.round(days / 30);
		if (months < 18) return `${months} month${months === 1 ? '' : 's'} ago`;
		const years = (days / 365).toFixed(1).replace(/\.0$/, '');
		return `${years} year${years === '1' ? '' : 's'} ago`;
	}

	async function loadTargets() {
		targetsLoading = true;
		targetsError = null;
		targetsMissing = false;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/hive/targets`);
			if (res.status === 400) {
				targetsMissing = true;
				targets = [];
				return;
			}
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = (await res.json()) as HiveTarget[];
			targets = Array.isArray(data) ? data : [];
			if (targets.length === 0) {
				targetsMissing = true;
			}
		} catch (e: any) {
			targetsError = e?.message ?? 'Failed to load Hive targets.';
			targets = [];
		} finally {
			targetsLoading = false;
		}
	}

	async function loadModels() {
		loadingModels = true;
		modelsError = null;
		try {
			const params = new URLSearchParams();
			// No target_id → backend aggregates across every configured Hive
			// and tags each row with target_id/target_url/target_name.
			if (query.trim()) params.set('q', query.trim());
			if (scopeFilter.trim()) params.set('scope', scopeFilter.trim());
			if (runtimeFilter) params.set('runtime', runtimeFilter);
			if (familyFilter.trim()) params.set('family', familyFilter.trim());
			params.set('page', String(page));
			params.set('page_size', String(PAGE_SIZE));
			const res = await fetch(`${getBackendHttpBase()}/api/hive/models?${params.toString()}`);
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
			const res = await fetch(`${getBackendHttpBase()}/api/hive/models/installed`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			const items = Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : [];
			installed = items as Installed[];
		} catch (e: any) {
			installedError = e?.message ?? 'Failed to load installed models.';
			installed = [];
		} finally {
			loadingInstalled = false;
		}
	}

	async function loadActiveAssignments() {
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/hive/models/active-assignments`);
			if (!res.ok) return;
			const data = await res.json();
			const items = Array.isArray(data?.items) ? data.items : [];
			activeAssignments = items as ActiveAssignment[];
		} catch {
			// Active assignments are decorative — keep the page functional on failure.
		}
	}

	function entryAlgorithmId(entry: Installed): string {
		return `${entry.bundled ? 'bundled:' : 'hive:'}${entry.local_id}`;
	}

	async function readApiError(res: Response, fallback: string): Promise<string> {
		const text = await res.text().catch(() => '');
		if (!text) return fallback;
		try {
			const parsed = JSON.parse(text);
			if (typeof parsed?.detail === 'string') return parsed.detail;
			if (typeof parsed?.message === 'string') return parsed.message;
		} catch {
			// Not JSON — fall through and return the raw text.
		}
		return text;
	}

	function activeLabelsFor(entry: Installed): string[] {
		const id = entryAlgorithmId(entry);
		return activeAssignments
			.filter((assignment) => assignment.algorithm_id === id)
			.map((assignment) => assignment.label);
	}

	function toggleDetails(localId: string) {
		expandedDetailsId = expandedDetailsId === localId ? null : localId;
	}

	async function loadDownloads() {
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/hive/downloads`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			const next: Job[] = Array.isArray(data?.jobs) ? (data.jobs as Job[]) : [];

			const prevActive = new Set(
				jobs.filter((j) => j.status === 'queued' || j.status === 'downloading').map((j) => j.job_id)
			);
			let anyFinished = false;
			for (const job of next) {
				if (prevActive.has(job.job_id) && (job.status === 'done' || job.status === 'failed')) {
					anyFinished = true;
					break;
				}
			}

			jobs = next;

			if (anyFinished) {
				void loadInstalled();
				void loadActiveAssignments();
				if (tab === 'available') {
					void loadModels();
				}
			}
		} catch {
			// Silent — the download poll runs in the background and any
			// surfaced error already comes via actionError on enqueue. Job
			// failures are surfaced through the failed-job alert.
		}
	}

	function resetFilters() {
		query = '';
		scopeFilter = '';
		runtimeFilter = '';
		familyFilter = '';
		page = 1;
	}

	async function ensureDetail(
		modelId: string,
		targetId: string | null | undefined
	): Promise<ModelDetail | null> {
		if (!targetId) return null;
		const cached = detailCache.get(modelId);
		if (cached) return cached;
		try {
			const params = new URLSearchParams();
			params.set('target_id', targetId);
			const res = await fetch(
				`${getBackendHttpBase()}/api/hive/models/${encodeURIComponent(modelId)}?${params.toString()}`
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

	async function handleDownload(model: ModelSummary) {
		const targetId = model.target_id;
		if (!targetId) return;
		actionError = null;
		downloadingModelId = model.id;
		try {
			const params = new URLSearchParams();
			params.set('target_id', targetId);
			params.set('all', 'true');
			const res = await fetch(
				`${getBackendHttpBase()}/api/hive/models/${encodeURIComponent(model.id)}/download?${params.toString()}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				throw new Error(await readApiError(res, `HTTP ${res.status}`));
			}
			// Quiet flow: kick off the silent poll loop and let the Installed
			// list refresh itself when the download finishes. No toast, no
			// tab — keep the operator's attention on the model list.
			await loadDownloads();
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to enqueue download.';
		} finally {
			downloadingModelId = null;
		}
	}

	// Activate a model for exactly ONE subsystem slot — 1:1 with the TOML, no
	// fan-out and no scope fallback. The backend allows assigning a model to a
	// slot outside its training scope (we flag it in the hover list), so there's
	// no "valid?" gate here.
	async function handleActivateForSlot(entry: Installed, slot: ActiveAssignment) {
		const id = entryAlgorithmId(entry);
		actionError = null;
		activatingAlgorithmId = id;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/hive/models/activate`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ algorithm_id: id, scope: slot.scope, role: slot.role })
			});
			if (!res.ok) {
				throw new Error(await readApiError(res, `HTTP ${res.status}`));
			}
			await loadActiveAssignments();
			openActivateId = null;
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to activate model.';
		} finally {
			activatingAlgorithmId = null;
		}
	}

	async function handleCleanupUnused() {
		// Sweep up: entries that aren't bundled, aren't currently active,
		// and either are flagged as not-deployable on this sorter or just
		// nobody uses them.
		const candidates = installed.filter(
			(entry) =>
				!entry.bundled && (entry.compatible === false || activeLabelsFor(entry).length === 0)
		);
		if (candidates.length === 0) {
			// No-op — the unused-count badge in the header already tells
			// the operator there's nothing to do.
			return;
		}
		const summary = candidates.map((entry) => entry.name).join('\n  • ');
		if (
			!confirm(
				`Remove ${candidates.length} unused downloaded model${candidates.length === 1 ? '' : 's'}?\n\n  • ${summary}`
			)
		) {
			return;
		}
		actionError = null;
		cleaningUp = true;
		try {
			let removed = 0;
			const failures: string[] = [];
			for (const entry of candidates) {
				try {
					const res = await fetch(
						`${getBackendHttpBase()}/api/hive/models/installed/${encodeURIComponent(entry.local_id)}`,
						{ method: 'DELETE' }
					);
					if (!res.ok) {
						failures.push(`${entry.name}: ${await readApiError(res, `HTTP ${res.status}`)}`);
						continue;
					}
					removed += 1;
				} catch (e: any) {
					failures.push(`${entry.name}: ${e?.message ?? 'request failed'}`);
				}
			}
			await loadInstalled();
			if (tab === 'available') {
				await loadModels();
			}
			if (failures.length > 0) {
				actionError = `Removed ${removed}, ${failures.length} failed:\n${failures.join('\n')}`;
			}
		} finally {
			cleaningUp = false;
		}
	}

	async function handleDelete(entry: Installed) {
		if (!confirm(`Remove the installed model "${entry.name}" from this sorter?`)) return;
		actionError = null;
		deletingLocalId = entry.local_id;
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/hive/models/installed/${encodeURIComponent(entry.local_id)}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) {
				throw new Error(await readApiError(res, `HTTP ${res.status}`));
			}
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
		if (tab === 'available') {
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
			void loadActiveAssignments();
		}
	});

	$effect(() => {
		// Keep polling silently while a download is in flight so the
		// Installed list refreshes the moment it lands. No tab to render — the
		// poll just drives the auto-refresh in loadDownloads().
		if (hasActiveJob) {
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
			await Promise.all([loadInstalled(), loadDownloads(), loadActiveAssignments()]);
		})();
		return () => {
			stopPolling();
		};
	});

	function setTab(next: 'available' | 'installed') {
		tab = next;
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

	function targetName(id: string): string {
		return targets.find((t) => t.id === id)?.name ?? id;
	}

	function targetUrl(id: string | null | undefined): string | null {
		if (!id) return null;
		return targets.find((t) => t.id === id)?.url ?? null;
	}

	function hostFromUrl(url: string | null | undefined): string | null {
		if (!url) return null;
		return url.replace(/^https?:\/\//, '').replace(/\/+$/, '');
	}

	function shortSha(sha: string | null | undefined): string {
		if (!sha) return '—';
		return `${sha.slice(0, 12)}…`;
	}
</script>

<div class="grid gap-5">
	<!-- ───────────────────── Action feedback ─────────────────────
	     Errors only — success states are conveyed by the Installed list
	     itself (Active pill, model appearing/disappearing). -->
	{#if actionError}
		<Alert variant="danger">
			<div class="whitespace-pre-line">{actionError}</div>
		</Alert>
	{/if}

	<!-- ───────────────────── Catalog manager ───────────────────── -->
	{#if targetsLoading}
		<Alert variant="info">Loading Hive targets…</Alert>
	{:else if targetsMissing && installed.length === 0}
		<Alert variant="info">
			No Hive target configured and no models installed. Configure a target in the Hive card to
			browse the catalog.
		</Alert>
	{:else if targetsError}
		<Alert variant="danger">{targetsError}</Alert>
	{/if}

	{#if !targetsLoading && !targetsError}
		<div class="border border-border bg-surface">
			<!-- Section header: tabs + target picker + refresh -->
			<header
				class="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg px-2"
			>
				<nav class="-mb-px flex items-stretch" aria-label="Models view">
					<button
						type="button"
						onclick={() => setTab('installed')}
						class={`border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${tab === 'installed' ? 'border-primary text-text' : 'border-transparent text-text-muted hover:text-text'}`}
					>
						Installed
						{#if installed.length > 0}
							<span class="ml-1 text-xs font-normal text-text-muted">
								{installed.length}
							</span>
						{/if}
					</button>
					{#if !targetsMissing}
						<button
							type="button"
							onclick={() => setTab('available')}
							class={`border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${tab === 'available' ? 'border-primary text-text' : 'border-transparent text-text-muted hover:text-text'}`}
						>
							Browse Hive
						</button>
					{/if}
				</nav>

				<div class="flex items-center gap-2 px-2 py-2">
					<Tooltip text="Refresh current view">
						<Button
							variant="ghost"
							size="sm"
							onclick={() => {
								if (tab === 'available') void loadModels();
								if (tab === 'installed') {
									void loadInstalled();
									void loadActiveAssignments();
								}
							}}
						>
							<RefreshCw size={14} />
						</Button>
					</Tooltip>
				</div>
			</header>

			<div class="p-4">
				{#if tab === 'available'}
					<div class="flex flex-col gap-4">
						<div class="flex flex-wrap items-center gap-2">
							<div class="relative w-full sm:min-w-[16rem] sm:flex-1">
								<Search
									size={14}
									class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-muted"
								/>
								<input
									bind:value={query}
									oninput={onFilterChange}
									type="text"
									placeholder="Search name or slug"
									class="w-full border border-border bg-surface py-2 pr-3 pl-9 text-sm text-text focus:border-primary focus:outline-none"
								/>
							</div>
							<details class="group">
								<summary
									class="cursor-pointer list-none border border-border bg-surface px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg"
								>
									<span class="inline-flex items-center gap-1.5">
										<ChevronRight size={14} class="transition-transform group-open:rotate-90" />
										Advanced filters
									</span>
								</summary>
								<div class="mt-2 grid gap-2 sm:grid-cols-3">
									<input
										bind:value={scopeFilter}
										oninput={onFilterChange}
										type="text"
										placeholder="Scope (e.g. brick, minifig)"
										class="border border-border bg-surface px-3 py-2 text-sm text-text"
									/>
									<select
										bind:value={runtimeFilter}
										onchange={onFilterChange}
										class="border border-border bg-surface px-3 py-2 text-sm text-text"
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
										class="border border-border bg-surface px-3 py-2 text-sm text-text"
									/>
								</div>
							</details>
						</div>

						<div class="flex items-center justify-between text-xs text-text-muted">
							<span>
								{#if loadingModels}
									Loading models…
								{:else}
									{modelsTotal} model{modelsTotal === 1 ? '' : 's'}{modelsPages > 1
										? ` · page ${page} of ${modelsPages}`
										: ''}
								{/if}
							</span>
							{#if query || scopeFilter || runtimeFilter || familyFilter}
								<button
									type="button"
									onclick={resetFilters}
									class="text-text-muted underline-offset-2 hover:text-text hover:underline"
								>
									Clear filters
								</button>
							{/if}
						</div>

						{#if modelsError}
							<Alert variant="danger">{modelsError}</Alert>
						{/if}

						{#if !loadingModels && models.length === 0 && !modelsError}
							<div class="border border-border bg-bg px-4 py-6 text-center text-sm text-text-muted">
								No models found.
							</div>
						{:else}
							<ul class="flex flex-col">
								{#each models as model, idx (model.id)}
									{@const jobActive = activeJobModelIds.has(model.id)}
									{@const browseHref = model.target_url
										? `${model.target_url.replace(/\/+$/, '')}/models/${model.id}`
										: null}
									<li
										class={`flex flex-wrap items-center justify-between gap-3 border border-border bg-surface px-4 py-3 ${idx > 0 ? '-mt-px' : ''}`}
									>
										<div class="min-w-0 flex-1">
											<div class="flex flex-wrap items-center gap-2">
												{#if browseHref}
													<a
														href={browseHref}
														target="_blank"
														rel="noopener noreferrer"
														class="font-mono text-sm font-medium text-text hover:text-primary hover:underline"
														title={`Open in source Hive: ${browseHref}`}
													>
														{model.name}
													</a>
												{:else}
													<span class="font-mono text-sm font-medium text-text">{model.name}</span>
												{/if}
												{#if model.installed}
													<span
														class="inline-flex items-center gap-1 bg-text-muted/20 px-2 py-0.5 text-xs font-semibold tracking-wider text-text uppercase"
													>
														<CheckCircle2 size={10} />
														Installed
													</span>
												{/if}
											</div>
											<div
												class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted"
											>
												<span>{model.model_family}</span>
												<span aria-hidden="true">·</span>
												<span>v{model.version}</span>
												{#if model.variant_runtimes.length > 0}
													<span aria-hidden="true">·</span>
													<span>
														{model.variant_runtimes.length} format{model.variant_runtimes.length ===
														1
															? ''
															: 's'}
														<span class="text-text-muted/70">
															({model.variant_runtimes.join(', ')})
														</span>
													</span>
												{/if}
												<span aria-hidden="true">·</span>
												<Tooltip text={`Published ${formatDate(model.published_at)}`}>
													<span class="text-text">
														published {formatRelativeAge(model.published_at) ??
															formatDate(model.published_at)}
													</span>
												</Tooltip>
												{#if model.target_url}
													<span aria-hidden="true">·</span>
													<span
														class="font-mono text-text-muted/80"
														title={`Source Hive: ${model.target_url}`}
													>
														{model.target_url.replace(/^https?:\/\//, '')}
													</span>
												{/if}
											</div>
										</div>
										<Button
											variant={model.installed ? 'secondary' : 'primary'}
											size="sm"
											disabled={jobActive || downloadingModelId === model.id || !model.target_id}
											loading={downloadingModelId === model.id || jobActive}
											onclick={() => void handleDownload(model)}
										>
											{#if !(downloadingModelId === model.id || jobActive)}
												<Download size={12} />
											{/if}
											<span>
												{jobActive
													? 'Downloading…'
													: downloadingModelId === model.id
														? 'Starting…'
														: model.installed
															? 'Download again'
															: 'Download'}
											</span>
										</Button>
									</li>
								{/each}
							</ul>
						{/if}

						{#if modelsPages > 1}
							<div class="flex items-center justify-end gap-2 text-xs">
								<Button variant="secondary" size="sm" onclick={prevPage} disabled={page <= 1}>
									Previous
								</Button>
								<span class="text-text-muted">Page {page} of {modelsPages}</span>
								<Button
									variant="secondary"
									size="sm"
									onclick={nextPage}
									disabled={page >= modelsPages}
								>
									Next
								</Button>
							</div>
						{/if}
					</div>
				{:else if tab === 'installed'}
					{@const unusedCount = installed.filter(
						(entry) =>
							!entry.bundled && (entry.compatible === false || activeLabelsFor(entry).length === 0)
					).length}
					<div class="flex flex-col gap-4">
						{#if installedError}
							<Alert variant="danger">{installedError}</Alert>
						{/if}

						{#if installed.length > 0}
							<div
								class="flex flex-wrap items-center justify-between gap-3 text-xs text-text-muted"
							>
								<span>
									{installed.length} installed
									{#if unusedCount > 0}
										· <span class="text-warning-dark dark:text-warning">{unusedCount} unused</span>
									{/if}
								</span>
								{#if unusedCount > 0}
									<Button
										variant="ghost"
										size="sm"
										onclick={() => void handleCleanupUnused()}
										disabled={cleaningUp}
										loading={cleaningUp}
									>
										<Trash2 size={12} />
										<span>
											{cleaningUp ? 'Cleaning up' : `Cleanup ${unusedCount} unused`}
										</span>
									</Button>
								{/if}
							</div>
						{/if}

						{#if loadingInstalled}
							<div class="text-sm text-text-muted">Loading installed models…</div>
						{:else if installed.length === 0}
							<div class="border border-border bg-bg px-4 py-6 text-center text-sm text-text-muted">
								No models installed yet. Open <span class="font-medium text-text">Browse Hive</span> to
								download one.
							</div>
						{:else}
							<ul class="flex flex-col">
								{#each installed as entry, idx (entry.local_id)}
									{@const activeLabels = activeLabelsFor(entry)}
									{@const isActive = activeLabels.length > 0}
									{@const isExpanded = expandedDetailsId === entry.local_id}
									{@const algorithmId = entryAlgorithmId(entry)}
									{@const ageIso = entry.trained_at ?? entry.downloaded_at}
									{@const ageRelative = formatRelativeAge(ageIso)}
									{@const isCompatible = entry.compatible !== false}
									{@const hiveBase = targetUrl(entry.target_id)}
									{@const detailHref =
										!entry.bundled && hiveBase
											? `${hiveBase.replace(/\/+$/, '')}/models/${entry.model_id}`
											: null}
									<li
										class={`border ${idx > 0 ? '-mt-px' : ''} ${isActive ? 'border-success bg-success/[0.06]' : !isCompatible ? 'border-border bg-bg opacity-70' : 'border-border bg-surface'}`}
									>
										<div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
											<div class="min-w-0 flex-1">
												<div class="flex flex-wrap items-center gap-2">
													{#if detailHref}
														<a
															href={detailHref}
															target="_blank"
															rel="noopener noreferrer"
															class="font-mono text-sm font-medium text-text hover:text-primary hover:underline"
															title={`Open in source Hive: ${detailHref}`}
														>
															{entry.name}
														</a>
													{:else}
														<span class="font-mono text-sm font-medium text-text">
															{entry.name}
														</span>
													{/if}
													{#if entry.bundled}
														<span
															class="inline-flex items-center bg-text-muted/20 px-2 py-0.5 text-xs font-semibold tracking-wider text-text uppercase"
														>
															Bundled
														</span>
													{/if}
													{#if !isCompatible}
														<Tooltip
															text={`Variant runtime "${entry.variant_runtime}" cannot be loaded by the sorter — only ONNX, NCNN, Hailo and RKNN are deployable.`}
														>
															<span
																class="inline-flex items-center bg-warning/20 px-2 py-0.5 text-xs font-semibold tracking-wider text-warning-dark uppercase dark:text-warning"
															>
																Not supported
															</span>
														</Tooltip>
													{/if}
												</div>
												<div
													class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted"
												>
													<span>{entry.model_family}</span>
													<span aria-hidden="true">·</span>
													<span>{entry.variant_runtime}</span>
													<span aria-hidden="true">·</span>
													<span>{formatSize(entry.size_bytes)}</span>
													{#if ageIso}
														<span aria-hidden="true">·</span>
														<Tooltip
															text={`${entry.trained_at ? 'Trained' : 'Downloaded'} ${formatDate(ageIso)}`}
														>
															<span class="text-text">
																{entry.trained_at ? 'trained' : 'downloaded'}
																{ageRelative}
															</span>
														</Tooltip>
													{/if}
													{#if entry.bundled}
														<span aria-hidden="true">·</span>
														<span>bundled</span>
													{:else if hostFromUrl(targetUrl(entry.target_id))}
														<span aria-hidden="true">·</span>
														<span
															class="font-mono text-text-muted/80"
															title={`From Hive: ${targetUrl(entry.target_id)}`}
														>
															{hostFromUrl(targetUrl(entry.target_id))}
														</span>
													{/if}
												</div>
											</div>

											<div class="flex flex-wrap items-center gap-2">
												{#if !isCompatible}
													<span class="px-3 py-1.5 text-xs text-text-muted"> Cannot activate </span>
												{:else}
													<!-- Tap/hover-expand activate: assign this model to a single
											     subsystem at a time, 1:1 with the TOML, no fallback.
											     The tap toggle makes it reachable on the CM5 touch tablet. -->
													<div class="group relative">
														<button
															type="button"
															onclick={() =>
																(openActivateId =
																	openActivateId === algorithmId ? null : algorithmId)}
															class={`inline-flex items-center gap-1.5 border px-3 py-1.5 text-sm transition-colors ${
																isActive
																	? 'border-success/40 bg-success/[0.08] text-text'
																	: 'border-border bg-surface text-text hover:bg-bg'
															}`}
														>
															{#if isActive}
																<CheckCircle2 size={14} class="shrink-0 text-success" />
																<span>Active: {activeLabels.join(', ')}</span>
															{:else}
																<span>Activate</span>
															{/if}
															<ChevronDown size={13} class="opacity-70" />
														</button>
														<div
															class={`absolute top-full right-0 z-30 mt-px w-[min(16rem,calc(100vw-2rem))] border border-border bg-surface shadow-lg transition-opacity duration-100 group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 ${
																openActivateId === algorithmId
																	? 'visible opacity-100'
																	: 'invisible opacity-0'
															}`}
														>
															<div
																class="border-b border-border px-3 py-2 text-xs font-semibold tracking-wider text-text-muted uppercase"
															>
																Activate for subsystem
															</div>
															{#if activeAssignments.length === 0}
																<div class="px-3 py-2 text-sm text-text-muted">
																	No detection subsystems on this machine setup.
																</div>
															{/if}
															{#each activeAssignments as slot (slot.scope + (slot.role ?? ''))}
																{@const slotActive = slot.algorithm_id === algorithmId}
																{@const designedFor = (entry.registry_scopes ?? []).includes(
																	slot.registry_scope ?? '__none__'
																)}
																<button
																	type="button"
																	disabled={activatingAlgorithmId === algorithmId}
																	onclick={() => void handleActivateForSlot(entry, slot)}
																	class={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-bg disabled:opacity-60 ${
																		slotActive ? 'bg-success/[0.08]' : ''
																	}`}
																>
																	<span class="flex min-w-0 items-center gap-2">
																		{#if slotActive}
																			<CheckCircle2 size={14} class="shrink-0 text-success" />
																		{:else}
																			<span class="inline-block w-[14px] shrink-0"></span>
																		{/if}
																		<span class="truncate text-text">{slot.label}</span>
																	</span>
																	{#if !designedFor}
																		<span
																			class="inline-flex shrink-0 items-center bg-warning/20 px-1.5 py-0.5 text-xs font-medium tracking-wider text-warning-dark uppercase dark:text-warning"
																		>
																			not designed for this
																		</span>
																	{/if}
																</button>
															{/each}
														</div>
													</div>
												{/if}
												{#if !entry.bundled}
													<Tooltip text="Remove this downloaded model">
														<Button
															variant="ghost"
															size="sm"
															disabled={deletingLocalId === entry.local_id}
															onclick={() => void handleDelete(entry)}
														>
															<Trash2 size={14} class="text-danger" />
														</Button>
													</Tooltip>
												{/if}
												<button
													type="button"
													aria-expanded={isExpanded}
													aria-controls={`installed-details-${entry.local_id}`}
													onclick={() => toggleDetails(entry.local_id)}
													class="inline-flex items-center gap-1 px-1.5 py-1 text-xs text-text-muted transition-colors hover:text-text"
												>
													{#if isExpanded}
														<ChevronDown size={14} />
													{:else}
														<ChevronRight size={14} />
													{/if}
													<span>Details</span>
												</button>
											</div>
										</div>

										{#if isExpanded}
											<div
												id={`installed-details-${entry.local_id}`}
												class="border-t border-border bg-bg px-4 py-3"
											>
												<dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-xs">
													{#if entry.trained_at}
														<dt class="text-text-muted">Trained</dt>
														<dd class="text-text">
															{formatDate(entry.trained_at)}
															<span class="ml-1 text-text-muted">
																({formatRelativeAge(entry.trained_at)})
															</span>
														</dd>
													{/if}
													<dt class="text-text-muted">SHA-256</dt>
													<dd class="font-mono text-text" title={entry.sha256 ?? ''}>
														{shortSha(entry.sha256)}
													</dd>
													<dt class="text-text-muted">Size</dt>
													<dd class="text-text">{formatSize(entry.size_bytes)}</dd>
													<dt class="text-text-muted">
														{entry.bundled ? 'Source' : 'Downloaded'}
													</dt>
													<dd class="text-text">
														{entry.bundled
															? 'Shipped with sorter'
															: `${formatDate(entry.downloaded_at)} (${formatRelativeAge(entry.downloaded_at) ?? '—'})`}
													</dd>
													{#if !entry.bundled}
														<dt class="text-text-muted">Hive</dt>
														<dd class="font-mono break-all text-text">
															{targetUrl(entry.target_id) ?? targetName(entry.target_id ?? '')}
														</dd>
													{/if}
													<dt class="text-text-muted">Algorithm ID</dt>
													<dd class="font-mono break-all text-text">{algorithmId}</dd>
													<dt class="text-text-muted">Path</dt>
													<dd class="font-mono break-all text-text" title={entry.path}>
														{entry.path}
													</dd>
												</dl>
											</div>
										{/if}
									</li>
								{/each}
							</ul>
						{/if}
					</div>
				{/if}

				{#if jobs.some((job) => job.status === 'failed')}
					{@const failure = jobs.find((job) => job.status === 'failed')}
					<Alert variant="danger" class="mt-3">
						Download failed: {failure?.error ?? failure?.file_name ?? 'unknown error'}
					</Alert>
				{/if}
			</div>
		</div>
	{/if}
</div>
