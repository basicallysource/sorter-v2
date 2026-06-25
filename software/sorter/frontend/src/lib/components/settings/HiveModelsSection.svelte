<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase } from '$lib/backend';
	import { Alert, Button, Tooltip } from '$lib/components/primitives';
	import BenchmarkModal from './BenchmarkModal.svelte';
	import {
		Download,
		RefreshCw,
		Trash2,
		Search,
		CheckCircle2,
		ChevronDown,
		ChevronRight,
		Gauge,
		Zap
	} from 'lucide-svelte';

	type HiveTarget = { id: string; name: string; url: string };
	type ModelSummary = {
		id: string;
		slug: string;
		version: number;
		codename?: string | null;
		codename_color?: string | null;
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
		codename?: string | null;
		codename_color?: string | null;
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
	type ActiveAssignment = {
		scope: string;
		role: string | null;
		label: string;
		algorithm_id: string | null;
		registry_scope?: string;
		group?: string;
	};

	// A single logical model — one or more downloaded format variants collapsed
	// into one row, plus (for not-yet-downloaded models) the Hive catalog entry.
	type UnifiedModel = {
		key: string;
		name: string;
		codename: string | null;
		codename_color: string | null;
		model_family: string;
		installed: boolean;
		bundled: boolean;
		variants: Installed[];
		summary: ModelSummary | null;
	};

	const RUNTIME_OPTIONS = ['', 'onnx', 'ncnn', 'hailo', 'rknn', 'pytorch'] as const;
	const PAGE_SIZE = 20;

	let targets = $state<HiveTarget[]>([]);
	let targetsLoading = $state(true);
	let targetsError = $state<string | null>(null);
	let targetsMissing = $state(false);

	let expandedDetailsKey = $state<string | null>(null);

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

	let activeAssignments = $state<ActiveAssignment[]>([]);

	let jobs = $state<Job[]>([]);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let downloadingKey = $state<string | null>(null);
	let deletingKey = $state<string | null>(null);
	let activatingAlgorithmId = $state<string | null>(null);
	let cleaningUp = $state(false);
	let actionError = $state<string | null>(null);

	// Machine-recommended model format (rknn / onnx / …) — used to pick which
	// downloaded variant a row activates and benchmarks by default.
	let recommendedFormatId = $state<string | null>(null);

	let benchmarkOpen = $state(false);
	let benchmarkModel = $state<UnifiedModel | null>(null);

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
		return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' });
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
			if (targets.length === 0) targetsMissing = true;
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
			activeAssignments = Array.isArray(data?.items) ? (data.items as ActiveAssignment[]) : [];
		} catch {
			// Active assignments are decorative — keep the page functional on failure.
		}
	}

	async function loadRecommendedFormat() {
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/runtimes/formats`);
			if (!res.ok) return;
			const payload = await res.json();
			const fmts = Array.isArray(payload?.formats) ? payload.formats : [];
			let bestRank = Infinity;
			let bestFmt: string | null = null;
			let flaggedFmt: string | null = null;
			for (const f of fmts) {
				for (const o of f.options ?? []) {
					if (!o.available) continue;
					if (o.recommended) flaggedFmt = f.id;
					if (typeof o.rank === 'number' && o.rank < bestRank) {
						bestRank = o.rank;
						bestFmt = f.id;
					}
				}
			}
			recommendedFormatId = flaggedFmt ?? bestFmt;
		} catch {
			// Recommendation is advisory — fall back to first-variant order.
		}
	}

	function entryAlgorithmId(entry: Installed): string {
		return `${entry.bundled ? 'bundled:' : 'hive:'}${entry.local_id}`;
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

	function compatibleVariants(model: UnifiedModel): Installed[] {
		return model.variants.filter((v) => v.compatible !== false);
	}

	// The variant a row's Activate/Benchmark actions target: the machine-
	// recommended format if downloaded, else the first deployable variant.
	function activationVariant(model: UnifiedModel): Installed | null {
		const pool = compatibleVariants(model);
		if (pool.length === 0) return null;
		if (recommendedFormatId) {
			const match = pool.find(
				(v) => formatIdFromVariant(v.variant_runtime) === recommendedFormatId
			);
			if (match) return match;
		}
		return pool[0];
	}

	function activeLabelsForModel(model: UnifiedModel): string[] {
		const ids = new Set(model.variants.map(entryAlgorithmId));
		return activeAssignments
			.filter((a) => a.algorithm_id != null && ids.has(a.algorithm_id))
			.map((a) => a.label);
	}

	async function readApiError(res: Response, fallback: string): Promise<string> {
		const text = await res.text().catch(() => '');
		if (!text) return fallback;
		try {
			const parsed = JSON.parse(text);
			if (typeof parsed?.detail === 'string') return parsed.detail;
			if (typeof parsed?.message === 'string') return parsed.message;
		} catch {
			// Not JSON — return raw text.
		}
		return text;
	}

	function toggleDetails(key: string) {
		expandedDetailsKey = expandedDetailsKey === key ? null : key;
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
				void loadModels();
			}
		} catch {
			// Silent — the poll runs in the background; failures surface via the
			// failed-job alert.
		}
	}

	function resetFilters() {
		query = '';
		scopeFilter = '';
		runtimeFilter = '';
		familyFilter = '';
		page = 1;
	}

	async function handleDownload(model: UnifiedModel) {
		const summary = model.summary;
		const targetId = summary?.target_id;
		if (!summary || !targetId) return;
		actionError = null;
		downloadingKey = model.key;
		try {
			const params = new URLSearchParams();
			params.set('target_id', targetId);
			params.set('all', 'true');
			const res = await fetch(
				`${getBackendHttpBase()}/api/hive/models/${encodeURIComponent(summary.id)}/download?${params.toString()}`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await readApiError(res, `HTTP ${res.status}`));
			await loadDownloads();
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to enqueue download.';
		} finally {
			downloadingKey = null;
		}
	}

	// Activate for ALL designed channels in one click — the default. The backend
	// fans out to every detection slot the model's training scope claims.
	async function handleActivateAll(model: UnifiedModel) {
		const variant = activationVariant(model);
		if (!variant) return;
		const id = entryAlgorithmId(variant);
		actionError = null;
		activatingAlgorithmId = id;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/hive/models/activate`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ algorithm_id: id })
			});
			if (!res.ok) throw new Error(await readApiError(res, `HTTP ${res.status}`));
			await loadActiveAssignments();
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to activate model.';
		} finally {
			activatingAlgorithmId = null;
		}
	}

	// The exception path: bind the model to exactly ONE subsystem slot.
	async function handleActivateForSlot(model: UnifiedModel, slot: ActiveAssignment) {
		const variant = activationVariant(model);
		if (!variant) return;
		const id = entryAlgorithmId(variant);
		actionError = null;
		activatingAlgorithmId = id;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/hive/models/activate`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ algorithm_id: id, scope: slot.scope, role: slot.role })
			});
			if (!res.ok) throw new Error(await readApiError(res, `HTTP ${res.status}`));
			await loadActiveAssignments();
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to activate model.';
		} finally {
			activatingAlgorithmId = null;
		}
	}

	function openBenchmark(model: UnifiedModel) {
		benchmarkModel = model;
		benchmarkOpen = true;
	}

	async function deleteVariants(variants: Installed[]): Promise<string[]> {
		const failures: string[] = [];
		for (const entry of variants) {
			if (entry.bundled) continue;
			try {
				const res = await fetch(
					`${getBackendHttpBase()}/api/hive/models/installed/${encodeURIComponent(entry.local_id)}`,
					{ method: 'DELETE' }
				);
				if (!res.ok)
					failures.push(`${entry.name}: ${await readApiError(res, `HTTP ${res.status}`)}`);
			} catch (e: any) {
				failures.push(`${entry.name}: ${e?.message ?? 'request failed'}`);
			}
		}
		return failures;
	}

	async function handleDeleteModel(model: UnifiedModel) {
		const removable = model.variants.filter((v) => !v.bundled);
		if (removable.length === 0) return;
		const fmts = removable.map((v) => v.variant_runtime).join(', ');
		if (
			!confirm(
				`Remove "${model.name}" (${removable.length} format${removable.length === 1 ? '' : 's'}: ${fmts}) from this sorter?`
			)
		) {
			return;
		}
		actionError = null;
		deletingKey = model.key;
		try {
			const failures = await deleteVariants(removable);
			await Promise.all([loadInstalled(), loadModels(), loadActiveAssignments()]);
			if (failures.length > 0)
				actionError = `Some formats failed to delete:\n${failures.join('\n')}`;
		} finally {
			deletingKey = null;
		}
	}

	async function handleCleanupUnused() {
		const candidates = unifiedInstalled.filter(
			(m) =>
				!m.bundled && (compatibleVariants(m).length === 0 || activeLabelsForModel(m).length === 0)
		);
		if (candidates.length === 0) return;
		const list = candidates.map((m) => m.name).join('\n  • ');
		if (
			!confirm(
				`Remove ${candidates.length} unused model${candidates.length === 1 ? '' : 's'}?\n\n  • ${list}`
			)
		) {
			return;
		}
		actionError = null;
		cleaningUp = true;
		try {
			const failures: string[] = [];
			for (const model of candidates) {
				failures.push(...(await deleteVariants(model.variants.filter((v) => !v.bundled))));
			}
			await Promise.all([loadInstalled(), loadModels(), loadActiveAssignments()]);
			if (failures.length > 0) actionError = `${failures.length} failed:\n${failures.join('\n')}`;
		} finally {
			cleaningUp = false;
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
		pollTimer = setInterval(() => void loadDownloads(), 2000);
	}

	$effect(() => {
		// Catalog search/filters re-fetch the Hive side.
		void query;
		void scopeFilter;
		void runtimeFilter;
		void familyFilter;
		void page;
		if (!targetsMissing) void loadModels();
	});

	$effect(() => {
		if (hasActiveJob) startPolling();
		else stopPolling();
		return () => stopPolling();
	});

	onMount(() => {
		void (async () => {
			await loadTargets();
			await Promise.all([
				loadInstalled(),
				loadDownloads(),
				loadActiveAssignments(),
				loadRecommendedFormat()
			]);
		})();
		return () => stopPolling();
	});

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
	function safeCodenameColor(color: string | null | undefined): string | null {
		if (!color) return null;
		const trimmed = color.trim();
		return /^#[0-9a-fA-F]{6}$/.test(trimmed) ? trimmed : null;
	}
	function codenameDotStyle(color: string | null | undefined): string {
		return `background-color: ${safeCodenameColor(color) ?? 'var(--color-primary)'};`;
	}
	function runtimeLabel(runtime: string | null | undefined): string {
		return (runtime ?? '').toUpperCase() || '—';
	}
	function isAcceleratedRuntime(runtime: string | null | undefined): boolean {
		const r = (runtime ?? '').toLowerCase();
		return r.includes('rknn') || r.includes('hef') || r.includes('hailo');
	}

	// ── Unified model assembly ────────────────────────────────────────────
	// Installed/bundled variants collapse into one row per logical model.
	let unifiedInstalled = $derived.by<UnifiedModel[]>(() => {
		const map = new Map<string, Installed[]>();
		for (const e of installed) {
			const key = typeof e.model_id === 'string' && e.model_id ? e.model_id : `local:${e.local_id}`;
			const arr = map.get(key) ?? [];
			arr.push(e);
			map.set(key, arr);
		}
		const out: UnifiedModel[] = [];
		for (const [key, variants] of map) {
			const lead = activationVariant({ variants } as UnifiedModel) ?? variants[0];
			out.push({
				key,
				name: lead.name,
				codename: lead.codename ?? null,
				codename_color: lead.codename_color ?? null,
				model_family: lead.model_family,
				installed: true,
				bundled: variants.some((v) => v.bundled),
				variants,
				summary: null
			});
		}
		// Active first, then alphabetical — the operator cares about what's live.
		return out.sort((a, b) => {
			const aActive = activeLabelsForModel(a).length > 0 ? 0 : 1;
			const bActive = activeLabelsForModel(b).length > 0 ? 0 : 1;
			if (aActive !== bActive) return aActive - bActive;
			return a.name.localeCompare(b.name);
		});
	});

	// Catalog models not yet downloaded — greyed Download rows below the installed.
	let unifiedAvailable = $derived.by<UnifiedModel[]>(() => {
		const installedIds = new Set(
			installed.map((e) => e.model_id).filter((id): id is string => typeof id === 'string' && !!id)
		);
		return models
			.filter((m) => !m.installed && !installedIds.has(m.id))
			.map((m) => ({
				key: `hive:${m.id}`,
				name: m.name,
				codename: m.codename ?? null,
				codename_color: m.codename_color ?? null,
				model_family: m.model_family,
				installed: false,
				bundled: false,
				variants: [] as Installed[],
				summary: m
			}));
	});

	let visibleInstalled = $derived.by<UnifiedModel[]>(() => {
		const q = query.trim().toLowerCase();
		if (!q) return unifiedInstalled;
		return unifiedInstalled.filter(
			(m) =>
				m.name.toLowerCase().includes(q) ||
				(m.codename ?? '').toLowerCase().includes(q) ||
				m.model_family.toLowerCase().includes(q)
		);
	});

	let unusedCount = $derived(
		unifiedInstalled.filter(
			(m) =>
				!m.bundled && (compatibleVariants(m).length === 0 || activeLabelsForModel(m).length === 0)
		).length
	);
</script>

<div class="grid gap-5">
	{#if actionError}
		<Alert variant="danger">
			<div class="whitespace-pre-line">{actionError}</div>
		</Alert>
	{/if}

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
			<!-- Header: search + filters + refresh -->
			<header
				class="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg px-4 py-3"
			>
				<div class="relative min-w-[16rem] flex-1">
					<Search
						size={14}
						class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-muted"
					/>
					<input
						bind:value={query}
						oninput={onFilterChange}
						type="text"
						placeholder="Search models"
						class="w-full border border-border bg-surface py-2 pr-3 pl-9 text-sm text-text focus:border-primary focus:outline-none"
					/>
				</div>
				<div class="flex items-center gap-2">
					{#if unusedCount > 0}
						<Button
							variant="ghost"
							size="sm"
							onclick={() => void handleCleanupUnused()}
							disabled={cleaningUp}
							loading={cleaningUp}
						>
							<Trash2 size={12} />
							<span>{cleaningUp ? 'Cleaning up' : `Cleanup ${unusedCount} unused`}</span>
						</Button>
					{/if}
					<Tooltip text="Refresh">
						<Button
							variant="ghost"
							size="sm"
							onclick={() => {
								void loadInstalled();
								void loadActiveAssignments();
								void loadModels();
							}}
						>
							<RefreshCw size={14} />
						</Button>
					</Tooltip>
				</div>
			</header>

			{#if !targetsMissing}
				<div
					class="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2"
				>
					<details class="group">
						<summary
							class="cursor-pointer list-none text-sm text-text-muted transition-colors hover:text-text"
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
					{#if query || scopeFilter || runtimeFilter || familyFilter}
						<button
							type="button"
							onclick={resetFilters}
							class="text-sm text-text-muted underline-offset-2 hover:text-text hover:underline"
						>
							Clear filters
						</button>
					{/if}
				</div>
			{/if}

			<div class="p-4">
				{#if installedError}
					<Alert variant="danger">{installedError}</Alert>
				{/if}
				{#if modelsError}
					<Alert variant="danger" class="mt-2">{modelsError}</Alert>
				{/if}

				{#if loadingInstalled && installed.length === 0}
					<div class="text-sm text-text-muted">Loading models…</div>
				{:else}
					<ul class="flex flex-col">
						<!-- ── Downloaded / bundled models ── -->
						{#each visibleInstalled as model, idx (model.key)}
							{@const activeLabels = activeLabelsForModel(model)}
							{@const isActive = activeLabels.length > 0}
							{@const isExpanded = expandedDetailsKey === model.key}
							{@const compatible = compatibleVariants(model)}
							{@const canActivate = compatible.length > 0}
							{@const target = activationVariant(model)}
							{@const lead = model.variants[0]}
							{@const ageIso = lead.trained_at ?? lead.downloaded_at}
							{@const hiveBase = targetUrl(lead.target_id)}
							{@const detailHref =
								!model.bundled && hiveBase
									? `${hiveBase.replace(/\/+$/, '')}/models/${lead.model_id}`
									: null}
							{@const removable = model.variants.filter((v) => !v.bundled).length}
							<li
								class={`border ${idx > 0 ? '-mt-px' : ''} ${isActive ? 'border-success bg-success/[0.06]' : !canActivate ? 'border-border bg-bg opacity-70' : 'border-border bg-surface'}`}
							>
								<div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
									<div class="min-w-0 flex-1">
										<div class="flex flex-wrap items-center gap-2">
											{#if model.codename}
												<span
													class="inline-flex items-center gap-1.5 text-sm font-semibold text-text"
													title={`Hive codename: ${model.codename}`}
												>
													<span
														class="inline-block h-2.5 w-2.5"
														style={codenameDotStyle(model.codename_color)}
													></span>
													{model.codename}
												</span>
											{:else if detailHref}
												<a
													href={detailHref}
													target="_blank"
													rel="noopener noreferrer"
													class="font-mono text-sm font-medium text-text hover:text-primary hover:underline"
													title={`Open in source Hive: ${detailHref}`}
												>
													{model.name}
												</a>
											{:else}
												<span class="font-mono text-sm font-medium text-text">{model.name}</span>
											{/if}
											{#each model.variants as variant (variant.local_id)}
												{@const isTarget = target?.local_id === variant.local_id}
												<span
													class={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-semibold tracking-wider uppercase ${
														variant.compatible === false
															? 'border border-border text-text-muted opacity-60'
															: isAcceleratedRuntime(variant.variant_runtime)
																? 'border border-primary text-primary'
																: 'border border-border text-text-muted'
													}`}
													title={variant.compatible === false
														? `${runtimeLabel(variant.variant_runtime)} — not deployable on this sorter`
														: isTarget
															? `${runtimeLabel(variant.variant_runtime)} — recommended on this machine`
															: runtimeLabel(variant.variant_runtime)}
												>
													{#if isTarget && canActivate}
														<Zap size={10} />
													{/if}
													{runtimeLabel(variant.variant_runtime)}
												</span>
											{/each}
											{#if model.bundled}
												<span
													class="inline-flex items-center bg-text-muted/20 px-2 py-0.5 text-xs font-semibold tracking-wider text-text uppercase"
												>
													Bundled
												</span>
											{/if}
										</div>
										<div
											class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted"
										>
											{#if model.codename}
												{#if detailHref}
													<a
														href={detailHref}
														target="_blank"
														rel="noopener noreferrer"
														class="font-mono text-text-muted hover:text-primary hover:underline"
														>{model.name}</a
													>
												{:else}
													<span class="font-mono">{model.name}</span>
												{/if}
												<span aria-hidden="true">·</span>
											{/if}
											<span>{model.model_family}</span>
											<span aria-hidden="true">·</span>
											<span
												>{formatSize(
													model.variants.reduce((s, v) => s + (v.size_bytes || 0), 0)
												)}</span
											>
											{#if ageIso}
												<span aria-hidden="true">·</span>
												<Tooltip
													text={`${lead.trained_at ? 'Trained' : 'Downloaded'} ${formatDate(ageIso)}`}
												>
													<span class="text-text"
														>{lead.trained_at ? 'trained' : 'downloaded'}
														{formatRelativeAge(ageIso)}</span
													>
												</Tooltip>
											{/if}
											{#if model.bundled}
												<span aria-hidden="true">·</span>
												<span>bundled</span>
											{:else if hostFromUrl(hiveBase)}
												<span aria-hidden="true">·</span>
												<span class="font-mono text-text-muted/80" title={`From Hive: ${hiveBase}`}
													>{hostFromUrl(hiveBase)}</span
												>
											{/if}
										</div>
									</div>

									<div class="flex flex-wrap items-center gap-2">
										{#if !canActivate}
											<span class="px-3 py-1.5 text-xs text-text-muted">Cannot activate</span>
										{:else}
											<!-- Default = activate every designed channel; the dropdown
											     scopes it down to a single channel as the exception. -->
											<div class="flex items-stretch">
												<button
													type="button"
													disabled={activatingAlgorithmId ===
														(target ? entryAlgorithmId(target) : '')}
													onclick={() => void handleActivateAll(model)}
													class={`inline-flex items-center gap-1.5 border px-3 py-1.5 text-sm transition-colors disabled:opacity-60 ${
														isActive
															? 'border-success/40 bg-success/[0.08] text-text'
															: 'border-border bg-surface text-text hover:bg-bg'
													}`}
												>
													{#if isActive}
														<CheckCircle2 size={14} class="shrink-0 text-success" />
														<span>Active: {activeLabels.join(', ')}</span>
													{:else}
														<span>Activate all channels</span>
													{/if}
												</button>
												<div class="group relative">
													<button
														type="button"
														aria-label="Activate for a single channel"
														class="inline-flex h-full items-center border border-l-0 border-border bg-surface px-1.5 text-text transition-colors hover:bg-bg"
													>
														<ChevronDown size={14} class="opacity-70" />
													</button>
													<div
														class="invisible absolute top-full right-0 z-30 mt-px min-w-[16rem] border border-border bg-surface opacity-0 shadow-lg transition-opacity duration-100 group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
													>
														<div
															class="border-b border-border px-3 py-2 text-xs font-semibold tracking-wider text-text-muted uppercase"
														>
															Only for one channel
														</div>
														{#if activeAssignments.length === 0}
															<div class="px-3 py-2 text-sm text-text-muted">
																No detection subsystems on this machine setup.
															</div>
														{/if}
														{#each activeAssignments as slot (slot.scope + (slot.role ?? ''))}
															{@const slotActive =
																target != null && slot.algorithm_id === entryAlgorithmId(target)}
															{@const designedFor = (target?.registry_scopes ?? []).includes(
																slot.registry_scope ?? '__none__'
															)}
															<button
																type="button"
																disabled={activatingAlgorithmId ===
																	(target ? entryAlgorithmId(target) : '')}
																onclick={() => void handleActivateForSlot(model, slot)}
																class={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-bg disabled:opacity-60 ${slotActive ? 'bg-success/[0.08]' : ''}`}
															>
																<span class="flex min-w-0 items-center gap-2">
																	{#if slotActive}
																		<CheckCircle2 size={14} class="shrink-0 text-success" />
																	{:else}
																		<span class="inline-block w-[14px] shrink-0"></span>
																	{/if}
																	<span class="truncate text-text">Only {slot.label}</span>
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
											</div>
											<Tooltip text="Benchmark inference speed on this machine">
												<Button variant="secondary" size="sm" onclick={() => openBenchmark(model)}>
													<Gauge size={14} />
													<span>Benchmark</span>
												</Button>
											</Tooltip>
										{/if}
										{#if removable > 0}
											<Tooltip text="Remove this downloaded model">
												<Button
													variant="ghost"
													size="sm"
													disabled={deletingKey === model.key}
													onclick={() => void handleDeleteModel(model)}
												>
													<Trash2 size={14} class="text-danger" />
												</Button>
											</Tooltip>
										{/if}
										<button
											type="button"
											aria-expanded={isExpanded}
											aria-controls={`model-details-${model.key}`}
											onclick={() => toggleDetails(model.key)}
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
										id={`model-details-${model.key}`}
										class="border-t border-border bg-bg px-4 py-3"
									>
										<dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-xs">
											{#if lead.trained_at}
												<dt class="text-text-muted">Trained</dt>
												<dd class="text-text">
													{formatDate(lead.trained_at)}
													<span class="ml-1 text-text-muted"
														>({formatRelativeAge(lead.trained_at)})</span
													>
												</dd>
											{/if}
											<dt class="text-text-muted">Formats</dt>
											<dd class="text-text">
												{#each model.variants as v, vi (v.local_id)}
													{vi > 0 ? ', ' : ''}{runtimeLabel(v.variant_runtime)} ({formatSize(
														v.size_bytes
													)})
												{/each}
											</dd>
											<dt class="text-text-muted">{model.bundled ? 'Source' : 'Downloaded'}</dt>
											<dd class="text-text">
												{model.bundled
													? 'Shipped with sorter'
													: `${formatDate(lead.downloaded_at)} (${formatRelativeAge(lead.downloaded_at) ?? '—'})`}
											</dd>
											{#if !model.bundled}
												<dt class="text-text-muted">Hive</dt>
												<dd class="font-mono break-all text-text">
													{hiveBase ?? targetName(lead.target_id ?? '')}
												</dd>
											{/if}
											{#if target}
												<dt class="text-text-muted">Active algorithm ID</dt>
												<dd class="font-mono break-all text-text">{entryAlgorithmId(target)}</dd>
											{/if}
											<dt class="text-text-muted">SHA-256</dt>
											<dd class="font-mono text-text" title={lead.sha256 ?? ''}>
												{shortSha(lead.sha256)}
											</dd>
										</dl>
									</div>
								{/if}
							</li>
						{/each}

						<!-- ── Available on Hive (not yet downloaded) ── -->
						{#if !targetsMissing && unifiedAvailable.length > 0}
							<li
								class="-mt-px border-b border-border bg-bg px-4 py-2 text-xs font-semibold tracking-wider text-text-muted uppercase"
							>
								Available on Hive
								{#if loadingModels}<span class="ml-1 font-normal lowercase">· loading…</span>{/if}
							</li>
							{#each unifiedAvailable as model (model.key)}
								{@const summary = model.summary}
								{@const jobActive = summary != null && activeJobModelIds.has(summary.id)}
								{@const browseHref = summary?.target_url
									? `${summary.target_url.replace(/\/+$/, '')}/models/${summary.id}`
									: null}
								<li
									class="-mt-px flex flex-wrap items-center justify-between gap-3 border border-border bg-bg px-4 py-3 opacity-70"
								>
									<div class="min-w-0 flex-1">
										<div class="flex flex-wrap items-center gap-2">
											{#if model.codename}
												<span
													class="inline-flex items-center gap-1.5 text-sm font-semibold text-text"
													title={`Hive codename: ${model.codename}`}
												>
													<span
														class="inline-block h-2.5 w-2.5"
														style={codenameDotStyle(model.codename_color)}
													></span>
													{model.codename}
												</span>
											{:else if browseHref}
												<a
													href={browseHref}
													target="_blank"
													rel="noopener noreferrer"
													class="font-mono text-sm font-medium text-text hover:text-primary hover:underline"
													>{model.name}</a
												>
											{:else}
												<span class="font-mono text-sm font-medium text-text">{model.name}</span>
											{/if}
										</div>
										<div
											class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-muted"
										>
											<span>{model.model_family}</span>
											{#if summary}
												<span aria-hidden="true">·</span>
												<span>v{summary.version}</span>
												{#if summary.variant_runtimes.length > 0}
													<span aria-hidden="true">·</span>
													<span>{summary.variant_runtimes.join(', ')}</span>
												{/if}
												<span aria-hidden="true">·</span>
												<Tooltip text={`Published ${formatDate(summary.published_at)}`}>
													<span class="text-text"
														>published {formatRelativeAge(summary.published_at) ??
															formatDate(summary.published_at)}</span
													>
												</Tooltip>
												{#if summary.target_url}
													<span aria-hidden="true">·</span>
													<span
														class="font-mono text-text-muted/80"
														title={`Source Hive: ${summary.target_url}`}
														>{summary.target_url.replace(/^https?:\/\//, '')}</span
													>
												{/if}
											{/if}
										</div>
									</div>
									<Button
										variant="primary"
										size="sm"
										disabled={jobActive || downloadingKey === model.key || !summary?.target_id}
										loading={downloadingKey === model.key || jobActive}
										onclick={() => void handleDownload(model)}
									>
										{#if !(downloadingKey === model.key || jobActive)}
											<Download size={12} />
										{/if}
										<span
											>{jobActive
												? 'Downloading…'
												: downloadingKey === model.key
													? 'Starting…'
													: 'Download'}</span
										>
									</Button>
								</li>
							{/each}
						{/if}

						{#if visibleInstalled.length === 0 && unifiedAvailable.length === 0 && !loadingModels && !loadingInstalled}
							<li class="border border-border bg-bg px-4 py-6 text-center text-sm text-text-muted">
								{query ? 'No models match your search.' : 'No models installed or available.'}
							</li>
						{/if}
					</ul>
				{/if}

				{#if !targetsMissing && modelsPages > 1}
					<div class="mt-3 flex items-center justify-end gap-2 text-xs">
						<Button variant="secondary" size="sm" onclick={prevPage} disabled={page <= 1}
							>Previous</Button
						>
						<span class="text-text-muted">Hive page {page} of {modelsPages}</span>
						<Button variant="secondary" size="sm" onclick={nextPage} disabled={page >= modelsPages}
							>Next</Button
						>
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

{#if benchmarkModel}
	<BenchmarkModal
		bind:open={benchmarkOpen}
		modelName={benchmarkModel.codename ?? benchmarkModel.name}
		variants={compatibleVariants(benchmarkModel).map((v) => ({
			local_id: v.local_id,
			variant_runtime: v.variant_runtime
		}))}
		baseUrl={getBackendHttpBase()}
	/>
{/if}
