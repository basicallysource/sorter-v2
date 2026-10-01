<script lang="ts">
	import { confirmDialog } from '$lib/confirm.svelte';
	import { onMount } from 'svelte';
	import { getBackendHttpBase } from '$lib/backend';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import Boxes from '@lucide/svelte/icons/boxes';
	import Download from '@lucide/svelte/icons/download';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Trash2 from '@lucide/svelte/icons/trash';
	import CheckCircle2 from '@lucide/svelte/icons/circle-check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	type HiveTarget = { id: string; name: string; url: string };
	type ModelSummary = {
		id: string;
		slug: string;
		version: number;
		// Hive's human-friendly handle ("Ember") plus the swatch color it renders
		// alongside it. Null for models published before codenames existed.
		codename?: string | null;
		codename_color?: string | null;
		name: string;
		description: string | null;
		purpose?: string;
		model_family: string;
		scopes: string[] | null;
		is_public: boolean;
		experimental?: boolean;
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
		// `hive:<local_id>` for a Hive download, `local:<local_id>` for a model
		// someone put in the models directory by hand.
		algorithm_id: string;
		source: 'hive' | 'local';
		target_id: string | null;
		model_id: string | null;
		// Recorded in run.json at download time; absent for local models and
		// for installs that predate the field.
		codename?: string | null;
		codename_color?: string | null;
		variant_runtime: string;
		purpose?: string;
		// Installed correctly, but nothing on this machine consumes it yet.
		inert?: boolean;
		sha256: string;
		name: string;
		model_family: string;
		size_bytes: number;
		downloaded_at: string | null;
		// The Hive a download came from. Shown when no configured target names
		// it, e.g. for the default model a new machine installs on its own.
		source_url?: string | null;
		trained_at: string | null;
		path: string;
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

	// Hive publishes models for several purposes into one catalog. Detection
	// models drive the pipeline; piece-link matchers download and install fine
	// but nothing consumes them on the machine yet, so they're shown inert.
	const PURPOSE_OPTIONS = [
		{ value: '', label: 'All purposes' },
		{ value: 'detection', label: 'Detection' },
		{ value: 'piece_link', label: 'Piece link (experimental)' }
	] as const;
	const INERT_PURPOSES = new Set(['piece_link']);
	const PURPOSE_LABELS: Record<string, string> = {
		detection: 'Detection',
		piece_link: 'Piece link'
	};

	function purposeOf(item: { purpose?: string }): string {
		return item.purpose || 'detection';
	}

	function isInert(item: { purpose?: string; inert?: boolean }): boolean {
		return item.inert === true || INERT_PURPOSES.has(purposeOf(item));
	}

	// Hive identifies a model by its codename ("Ember") and a color swatch, with
	// the long descriptive name as the subtitle. Mirror that here so a model
	// reads the same on both sites. Anything without a codename — local
	// models, pre-codename publishes — keeps the descriptive name as its title.
	function titleOf(item: { codename?: string | null; name: string }): string {
		return item.codename || item.name;
	}

	function subtitleOf(item: { codename?: string | null; name: string }): string | null {
		return item.codename ? item.name : null;
	}

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
	let purposeFilter = $state('');
	let includeExperimental = $state(false);

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
			if (purposeFilter) params.set('purpose', purposeFilter);
			// Every piece-link matcher is published experimental, so asking for
			// that purpose implies you want experimental rows — otherwise the
			// filter would always come back empty.
			if (includeExperimental || INERT_PURPOSES.has(purposeFilter)) {
				params.set('include_experimental', 'true');
			}
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
		const id = entry.algorithm_id;
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
		purposeFilter = '';
		includeExperimental = false;
		page = 1;
	}

	async function ensureDetail(modelId: string, targetId: string | null | undefined): Promise<ModelDetail | null> {
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
		const id = entry.algorithm_id;
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
		} catch (e: any) {
			actionError = e?.message ?? 'Failed to activate model.';
		} finally {
			activatingAlgorithmId = null;
		}
	}

	async function handleCleanupUnused() {
		// Sweep up: Hive downloads that aren't currently active, and either are
		// flagged as not-deployable on this sorter or just nobody uses them.
		// Local models were put here by hand and can't be downloaded again, so
		// only an explicit Remove deletes one.
		const candidates = installed.filter(
			(entry) =>
				entry.source === 'hive' &&
				// An inert model has no scope to be active against, so "no active
				// assignment" doesn't mean unused — it means not wired up yet.
				// Sweeping those would delete a model the operator just fetched.
				!isInert(entry) &&
				(entry.compatible === false || activeLabelsFor(entry).length === 0)
		);
		if (candidates.length === 0) {
			// No-op — the unused-count badge in the header already tells
			// the operator there's nothing to do.
			return;
		}
		const summary = candidates.map((entry) => entry.name).join('\n  • ');
		if (
			!(await confirmDialog({
				title: `Remove ${candidates.length} unused downloaded model${candidates.length === 1 ? '' : 's'}?`,
				message: `  • ${summary}`,
				action: 'Remove them',
				danger: true
			}))
		)
			return;
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
						failures.push(
							`${entry.name}: ${await readApiError(res, `HTTP ${res.status}`)}`
						);
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
		if (
			!(await confirmDialog({
				title: 'Remove the model?',
				message: `Remove the installed model "${entry.name}" from this sorter?`,
				action: 'Remove the model',
				danger: true
			}))
		)
			return;
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
			void purposeFilter;
			void includeExperimental;
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

	function refreshView() {
		if (tab === 'available') void loadModels();
		if (tab === 'installed') {
			void loadInstalled();
			void loadActiveAssignments();
		}
	}

	function activateMenu(entry: Installed) {
		if (activeAssignments.length === 0) {
			return [{ label: 'No detection subsystems on this machine', disabled: true }];
		}
		return activeAssignments.map((slot) => ({
			label: slot.label,
			checked: slot.algorithm_id === entry.algorithm_id,
			hint: (entry.registry_scopes ?? []).includes(slot.registry_scope ?? '__none__')
				? undefined
				: 'Not designed for it',
			disabled: activatingAlgorithmId === entry.algorithm_id,
			onselect: () => void handleActivateForSlot(entry, slot)
		}));
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	<!-- Errors only: success shows in the lists themselves (the active model,
	     a model appearing or going). -->
	{#if actionError}
		<Alert tone="danger"><span class="whitespace-pre-line">{actionError}</span></Alert>
	{/if}

	{#if targetsLoading}
		<div class="flex items-center gap-2 text-sm text-ink-muted">
			<Spinner size={14} /> Loading the Hive settings
		</div>
	{:else if targetsMissing && installed.length === 0}
		<Alert tone="info">
			No Hive is set up and no models are installed. Set up a Hive in Settings, Hive to browse its
			models.
		</Alert>
	{:else if targetsError}
		<Alert tone="danger">{targetsError}</Alert>
	{/if}

	{#if !targetsLoading && !targetsError}
		<Panel flush>
			<div class="relative">
				<Tabs
					label="Models"
					inset
					value={tab}
					onchange={setTab}
					items={[
						{
							value: 'installed',
							label: 'Installed',
							count: installed.length > 0 ? installed.length : undefined
						},
						...(targetsMissing ? [] : [{ value: 'available' as const, label: 'Browse Hive' }])
					]}
				/>
				<div class="absolute top-1 right-2">
					<Button variant="ghost" size="sm" icon={RefreshCw} label="Refresh" onclick={refreshView} />
				</div>
			</div>

			{#if tab === 'available'}
				<div class="flex flex-col gap-3 px-(--pad-panel) py-4">
					<div class="flex flex-wrap items-center gap-2">
						<Input
							type="search"
							bind:value={query}
							oninput={onFilterChange}
							placeholder="Search a name or slug"
							class="min-w-64 flex-1"
						/>
						<div class="w-56">
							<Select
								label="Purpose"
								bind:value={purposeFilter}
								onchange={onFilterChange}
								options={PURPOSE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
							/>
						</div>
						<Popover label="More filters" placement="bottom-end">
							{#snippet trigger(props)}
								<Button {...props} icon={SlidersHorizontal}>More filters</Button>
							{/snippet}
							<div class="flex flex-col gap-4">
								<Field label="Scope" for="models-scope">
									<Input
										id="models-scope"
										bind:value={scopeFilter}
										oninput={onFilterChange}
										placeholder="brick, minifig"
									/>
								</Field>
								<Field label="Runtime" for="models-runtime">
									<Select
										id="models-runtime"
										bind:value={runtimeFilter}
										onchange={onFilterChange}
										options={RUNTIME_OPTIONS.map((o) => ({ value: o, label: o === '' ? 'Any runtime' : o }))}
									/>
								</Field>
								<Field label="Family" for="models-family">
									<Input id="models-family" bind:value={familyFilter} oninput={onFilterChange} />
								</Field>
								<Checkbox bind:checked={includeExperimental} onchange={onFilterChange}>
									Include experimental models
								</Checkbox>
							</div>
						</Popover>
					</div>

					<div class="flex items-center justify-between gap-3 text-sm text-ink-muted">
						{#if loadingModels}
							<span class="flex items-center gap-2"><Spinner size={14} /> Loading the models</span>
						{:else}
							<span>
								<span class="num">{modelsTotal}</span>
								{modelsTotal === 1 ? 'model' : 'models'}{modelsPages > 1
									? `, page ${page} of ${modelsPages}`
									: ''}
							</span>
						{/if}
						{#if query || scopeFilter || runtimeFilter || familyFilter || purposeFilter || includeExperimental}
							<Button variant="ghost" size="sm" onclick={resetFilters}>Clear the filters</Button>
						{/if}
					</div>

					{#if modelsError}
						<Alert tone="danger">{modelsError}</Alert>
					{/if}
				</div>

				{#if !loadingModels && models.length === 0 && !modelsError}
					<div class="px-(--pad-panel) pb-(--pad-panel)">
						<EmptyState icon={Boxes} title="No models found">Try other filters.</EmptyState>
					</div>
				{:else}
					<ul class="divide-y divide-line border-t border-line">
						{#each models as model (model.id)}
							{@const jobActive = activeJobModelIds.has(model.id)}
							{@const browseHref = model.target_url
								? `${model.target_url.replace(/\/+$/, '')}/models/${model.id}`
								: null}
							<li class="flex flex-wrap items-center justify-between gap-3 px-(--pad-panel) py-3">
								<div class="min-w-0 grow basis-64">
									<div class="flex flex-wrap items-center gap-2">
										{#if model.codename_color}
											<span
												class="size-3 shrink-0 rounded-check border border-line"
												style:background-color={model.codename_color}
												aria-hidden="true"
											></span>
										{/if}
										{#if browseHref}
											<a
												href={browseHref}
												target="_blank"
												rel="noopener noreferrer"
												class="font-mono text-sm font-medium text-ink hover:text-primary-ink hover:underline"
												title="Open it on its Hive"
											>
												{titleOf(model)}
											</a>
										{:else}
											<span class="font-mono text-sm font-medium text-ink">{titleOf(model)}</span>
										{/if}
										{#if model.installed}
											<Badge tone="success"><CheckCircle2 size={12} /> Installed</Badge>
										{/if}
										{#if model.experimental}
											<Badge tone="warning">Experimental</Badge>
										{/if}
										{#if isInert(model)}
											<Badge>{PURPOSE_LABELS[purposeOf(model)] ?? purposeOf(model)}</Badge>
										{/if}
									</div>
									{#if isInert(model)}
										<p class="mt-1 text-sm text-ink-muted">
											Downloads and installs, but nothing on this machine uses it yet.
										</p>
									{/if}
									<p class="mt-1 flex flex-wrap items-center gap-x-1.5 text-sm text-ink-muted">
										{#if subtitleOf(model)}
											<span class="font-mono text-ink">{subtitleOf(model)}</span>
											<span aria-hidden="true">·</span>
										{/if}
										<span>{model.model_family}</span>
										<span aria-hidden="true">·</span>
										<span>v{model.version}</span>
										{#if model.variant_runtimes.length > 0}
											<span aria-hidden="true">·</span>
											<span title={model.variant_runtimes.join(', ')}>
												{model.variant_runtimes.length}
												{model.variant_runtimes.length === 1 ? 'format' : 'formats'}
											</span>
										{/if}
										<span aria-hidden="true">·</span>
										<span title="Published {formatDate(model.published_at)}">
											Published {formatRelativeAge(model.published_at) ?? formatDate(model.published_at)}
										</span>
										{#if model.target_url}
											<span aria-hidden="true">·</span>
											<span class="font-mono">{model.target_url.replace(/^https?:\/\//, '')}</span>
										{/if}
									</p>
								</div>
								<Button
									variant={model.installed ? 'secondary' : 'primary'}
									size="sm"
									icon={Download}
									disabled={!model.target_id}
									loading={downloadingModelId === model.id || jobActive}
									onclick={() => void handleDownload(model)}
								>
									{jobActive
										? 'Downloading'
										: downloadingModelId === model.id
											? 'Starting'
											: model.installed
												? 'Download again'
												: 'Download'}
								</Button>
							</li>
						{/each}
					</ul>
				{/if}

				{#if modelsPages > 1}
					<div class="flex items-center justify-end gap-2 border-t border-line px-(--pad-panel) py-3 text-sm">
						<Button variant="ghost" size="sm" onclick={prevPage} disabled={page <= 1}>Previous</Button>
						<span class="text-ink-muted">Page {page} of {modelsPages}</span>
						<Button variant="ghost" size="sm" onclick={nextPage} disabled={page >= modelsPages}>
							Next
						</Button>
					</div>
				{/if}
			{:else if tab === 'installed'}
				{@const unusedCount = installed.filter(
					(entry) =>
						entry.source === 'hive' &&
						(entry.compatible === false || activeLabelsFor(entry).length === 0)
				).length}
				{#if installedError}
					<div class="px-(--pad-panel) pt-4"><Alert tone="danger">{installedError}</Alert></div>
				{/if}

				{#if installed.length > 0}
					<div class="flex flex-wrap items-center justify-between gap-3 px-(--pad-panel) py-3 text-sm text-ink-muted">
						<span>
							<span class="num">{installed.length}</span> installed{#if unusedCount > 0},
								<span class="text-warning-ink"><span class="num">{unusedCount}</span> unused</span>{/if}
						</span>
						{#if unusedCount > 0}
							<Button
								variant="ghost"
								size="sm"
								icon={Trash2}
								loading={cleaningUp}
								onclick={() => void handleCleanupUnused()}
							>
								Remove the {unusedCount} unused
							</Button>
						{/if}
					</div>
				{/if}

				{#if loadingInstalled}
					<div class="flex items-center gap-2 px-(--pad-panel) py-4 text-sm text-ink-muted">
						<Spinner size={14} /> Loading the installed models
					</div>
				{:else if installed.length === 0}
					<div class="p-(--pad-panel)">
						<EmptyState icon={Boxes} title="No models installed yet">
							Browse Hive to download one.
						</EmptyState>
					</div>
				{:else}
					<ul class="divide-y divide-line border-t border-line">
						{#each installed as entry (entry.local_id)}
							{@const activeLabels = activeLabelsFor(entry)}
							{@const isActive = activeLabels.length > 0}
							{@const isExpanded = expandedDetailsId === entry.local_id}
							{@const algorithmId = entry.algorithm_id}
							{@const ageIso = entry.trained_at ?? entry.downloaded_at}
							{@const ageRelative = formatRelativeAge(ageIso)}
							{@const isCompatible = entry.compatible !== false}
							{@const hiveBase = targetUrl(entry.target_id) ?? entry.source_url ?? null}
							{@const detailHref =
								entry.source === 'hive' && hiveBase
									? `${hiveBase.replace(/\/+$/, '')}/models/${entry.model_id}`
									: null}
							<li class={isActive ? 'bg-success-soft' : !isCompatible ? 'opacity-70' : ''}>
								<div class="flex flex-wrap items-center justify-between gap-3 px-(--pad-panel) py-3">
									<div class="min-w-0 grow basis-64">
										<div class="flex flex-wrap items-center gap-2">
											{#if entry.codename_color}
												<span
													class="size-3 shrink-0 rounded-check border border-line"
													style:background-color={entry.codename_color}
													aria-hidden="true"
												></span>
											{/if}
											{#if detailHref}
												<a
													href={detailHref}
													target="_blank"
													rel="noopener noreferrer"
													class="font-mono text-sm font-medium text-ink hover:text-primary-ink hover:underline"
													title="Open it on its Hive"
												>
													{titleOf(entry)}
												</a>
											{:else}
												<span class="font-mono text-sm font-medium text-ink">{titleOf(entry)}</span>
											{/if}
											{#if entry.source === 'local'}
												<span title="Put in this machine's models folder by hand, not downloaded from Hive">
													<Badge>Local</Badge>
												</span>
											{/if}
											{#if isInert(entry)}
												<Badge tone="warning">{PURPOSE_LABELS[purposeOf(entry)] ?? purposeOf(entry)}</Badge>
											{:else if !isCompatible}
												<span
													title="The sorter can't load a {entry.variant_runtime} variant: only ONNX, NCNN, Hailo and RKNN run here."
												>
													<Badge tone="warning">Not supported</Badge>
												</span>
											{/if}
										</div>
										{#if isInert(entry)}
											<p class="mt-1 text-sm text-ink-muted">
												Installed, but no part of the sorting reads this model yet.
											</p>
										{:else if isActive}
											<p class="mt-1 text-sm text-success-ink">Active for {activeLabels.join(', ')}</p>
										{/if}
										<p class="mt-1 flex flex-wrap items-center gap-x-1.5 text-sm text-ink-muted">
											{#if subtitleOf(entry)}
												<span class="font-mono text-ink">{subtitleOf(entry)}</span>
												<span aria-hidden="true">·</span>
											{/if}
											<span>{entry.model_family}</span>
											<span aria-hidden="true">·</span>
											<span>{entry.variant_runtime}</span>
											<span aria-hidden="true">·</span>
											<span class="num">{formatSize(entry.size_bytes)}</span>
											{#if ageIso}
												<span aria-hidden="true">·</span>
												<span title="{entry.trained_at ? 'Trained' : 'Downloaded'} {formatDate(ageIso)}">
													{entry.trained_at ? 'Trained' : 'Downloaded'}
													{ageRelative}
												</span>
											{/if}
											{#if entry.source === 'hive' && hostFromUrl(hiveBase)}
												<span aria-hidden="true">·</span>
												<span class="font-mono">{hostFromUrl(hiveBase)}</span>
											{/if}
										</p>
									</div>

									<div class="flex flex-wrap items-center gap-2">
										{#if isInert(entry)}
											<span class="text-sm text-ink-muted">Not wired up yet</span>
										{:else if !isCompatible}
											<span class="text-sm text-ink-muted">Can't be activated</span>
										{:else}
											<!-- One model per subsystem, as machine.toml has it, with no fallback. -->
											<Menu label="Activate {titleOf(entry)}" items={activateMenu(entry)} width="18rem">
												{#snippet trigger(props)}
													<Button
														{...props}
														size="sm"
														variant={isActive ? 'secondary' : 'primary'}
														icon={isActive ? CheckCircle2 : ChevronDown}
													>
														{isActive ? 'Active' : 'Activate'}
													</Button>
												{/snippet}
											</Menu>
										{/if}
										<Button
											variant="ghost"
											size="sm"
											icon={Trash2}
											label="Remove this model"
											disabled={deletingLocalId === entry.local_id}
											onclick={() => void handleDelete(entry)}
										/>
										<Button
											variant="ghost"
											size="sm"
											icon={isExpanded ? ChevronDown : ChevronRight}
											aria-expanded={isExpanded}
											aria-controls="installed-details-{entry.local_id}"
											onclick={() => toggleDetails(entry.local_id)}
										>
											Details
										</Button>
									</div>
								</div>

								{#if isExpanded}
									<div id="installed-details-{entry.local_id}" class="px-(--pad-panel) pb-3">
										<dl
											class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-control bg-well px-3 py-2.5 text-sm"
										>
											{#if entry.trained_at}
												<dt class="text-ink-muted">Trained</dt>
												<dd class="text-ink">
													{formatDate(entry.trained_at)}
													<span class="text-ink-muted">({formatRelativeAge(entry.trained_at)})</span>
												</dd>
											{/if}
											<dt class="text-ink-muted">SHA-256</dt>
											<dd class="font-mono text-ink" title={entry.sha256 ?? ''}>{shortSha(entry.sha256)}</dd>
											<dt class="text-ink-muted">Size</dt>
											<dd class="num text-ink">{formatSize(entry.size_bytes)}</dd>
											{#if entry.source === 'local'}
												<dt class="text-ink-muted">Source</dt>
												<dd class="text-ink">Put on this machine by hand</dd>
											{:else}
												<dt class="text-ink-muted">Downloaded</dt>
												<dd class="text-ink">
													{formatDate(entry.downloaded_at)}
													<span class="text-ink-muted">({formatRelativeAge(entry.downloaded_at) ?? 'unknown'})</span>
												</dd>
												<dt class="text-ink-muted">Hive</dt>
												<dd class="font-mono break-all text-ink">
													{hiveBase ?? targetName(entry.target_id ?? '')}
												</dd>
											{/if}
											<dt class="text-ink-muted">Algorithm ID</dt>
											<dd class="font-mono break-all text-ink">{algorithmId}</dd>
											<dt class="text-ink-muted">Path</dt>
											<dd class="font-mono break-all text-ink">{entry.path}</dd>
										</dl>
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			{/if}

			{#if jobs.some((job) => job.status === 'failed')}
				{@const failure = jobs.find((job) => job.status === 'failed')}
				<div class="border-t border-line px-(--pad-panel) py-3">
					<Alert tone="danger">
						The download failed: {failure?.error ?? failure?.file_name ?? 'unknown error'}
					</Alert>
				</div>
			{/if}
		</Panel>
	{/if}
</div>
