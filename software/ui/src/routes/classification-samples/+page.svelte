<script lang="ts">
	import { onMount } from 'svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { Search, X } from 'lucide-svelte';

	type SessionSummary = {
		session_id: string;
		session_name: string;
		created_at: number | null;
		processor: string;
		sample_count: number;
		completed_count: number;
		failed_count: number;
	};

	type SampleSummary = {
		session_id: string;
		session_name: string;
		sample_id: string;
		source: string;
		source_role?: string | null;
		capture_reason?: string | null;
		detection_scope?: string | null;
		camera?: string | null;
		preferred_camera?: string | null;
		captured_at: number | null;
		processor: string;
		detection_algorithm?: string | null;
		detection_openrouter_model?: string | null;
		detection_bbox_count?: number | null;
		distill_status: 'completed' | 'failed' | 'pending' | 'skipped';
		distill_detections?: number | null;
		retest_count: number;
		input_image_url?: string | null;
		overlay_image_url?: string | null;
		detail_url?: string | null;
	};

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let errorMsg = $state<string | null>(null);
	let sessions = $state<SessionSummary[]>([]);
	let samples = $state<SampleSummary[]>([]);
	let selectedSessionId = $state<string>('all');
	let selectedScope = $state<string>('all');
	let showFilters = $state(false);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function assetUrl(path: string | null | undefined): string | null {
		if (typeof path !== 'string' || !path) return null;
		if (path.startsWith('http://') || path.startsWith('https://')) return path;
		return `${currentBackendBaseUrl()}${path}`;
	}

	function timeAgo(timestamp: number | null | undefined): string {
		if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return '';
		const seconds = Math.floor(Date.now() / 1000 - timestamp);
		if (seconds < 60) return 'just now';
		if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
		if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
		return `${Math.floor(seconds / 86400)}d ago`;
	}

	function shortId(id: string): string {
		return id.length > 12 ? id.slice(-8) : id;
	}

	function modelShort(model: string | null | undefined): string {
		if (!model) return '';
		const parts = model.split('/');
		return parts[parts.length - 1] ?? model;
	}

	function scopeLabel(scope: string | null | undefined): string {
		if (!scope) return '';
		return scope.replace(/_/g, ' ');
	}

	function filterOptions(values: Array<string | null | undefined>): string[] {
		return [...new Set(values.filter((v): v is string => typeof v === 'string' && !!v))].sort();
	}

	function visibleSamples(): SampleSummary[] {
		return samples.filter((s) => {
			if (selectedSessionId !== 'all' && s.session_id !== selectedSessionId) return false;
			if (selectedScope !== 'all' && (s.detection_scope ?? 'unknown') !== selectedScope) return false;
			return true;
		});
	}

	function hasActiveFilters(): boolean {
		return selectedSessionId !== 'all' || selectedScope !== 'all';
	}

	function clearFilters() {
		selectedSessionId = 'all';
		selectedScope = 'all';
	}

	async function loadLibrary() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/classification/training/library`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			sessions = Array.isArray(payload?.sessions) ? payload.sessions : [];
			samples = Array.isArray(payload?.samples) ? payload.samples : [];
			if (
				selectedSessionId !== 'all' &&
				!sessions.some((s) => s.session_id === selectedSessionId)
			) {
				selectedSessionId = 'all';
			}
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to load classification samples.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadLibrary();
		}
	});

	onMount(() => {
		if (!samples.length && !loading) {
			void loadLibrary();
		}
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<AppHeader />

	<div class="flex flex-col gap-4">
		<div class="flex items-center justify-between gap-3">
			<h2 class="dark:text-text-dark text-lg font-semibold text-text">
				Samples
				{#if !loading}
					<span class="dark:text-text-muted-dark ml-1 text-sm font-normal text-text-muted">
						{visibleSamples().length}
					</span>
				{/if}
			</h2>
			<div class="flex items-center gap-2">
				{#if hasActiveFilters()}
					<button
						type="button"
						onclick={clearFilters}
						class="dark:text-text-muted-dark flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-red-500"
					>
						<X size={12} />
						Clear filters
					</button>
				{/if}
				<div class="flex gap-1">
					{#each [{ id: 'all', label: 'All' }, ...sessions.map((s) => ({ id: s.session_id, label: s.session_name }))] as tab}
						<button
							type="button"
							onclick={() => (selectedSessionId = tab.id)}
							class={`px-2.5 py-1 text-xs transition-colors ${
								selectedSessionId === tab.id
									? 'bg-text text-bg dark:bg-text-dark dark:text-bg-dark'
									: 'dark:text-text-muted-dark dark:hover:text-text-dark text-text-muted hover:text-text'
							}`}
						>
							{tab.label}
						</button>
					{/each}
				</div>
				{#if filterOptions(samples.map((s) => s.detection_scope)).length > 1}
					<select
						value={selectedScope}
						onchange={(e) => (selectedScope = e.currentTarget.value)}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark border border-border bg-bg px-2 py-1 text-xs text-text"
					>
						<option value="all">All scopes</option>
						{#each filterOptions(samples.map((s) => s.detection_scope)) as scope}
							<option value={scope}>{scopeLabel(scope)}</option>
						{/each}
					</select>
				{/if}
			</div>
		</div>

		{#if errorMsg}
			<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
				{errorMsg}
			</div>
		{/if}

		{#if !loading && visibleSamples().length === 0}
			<div class="dark:text-text-muted-dark py-16 text-center text-sm text-text-muted">
				{#if hasActiveFilters()}
					No samples match the current filters.
				{:else}
					No samples yet. Run a detection test to start building the library.
				{/if}
			</div>
		{:else}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
				{#each visibleSamples() as sample}
					<a
						href={sample.detail_url ?? '#'}
						class="dark:border-border-dark dark:bg-surface-dark group overflow-hidden border border-border bg-surface transition-all hover:border-sky-500/60 hover:shadow-sm"
					>
						<div class="dark:bg-bg-dark relative aspect-square bg-bg">
							{#if assetUrl(sample.overlay_image_url ?? sample.input_image_url)}
								<img
									src={assetUrl(sample.overlay_image_url ?? sample.input_image_url) ?? undefined}
									alt=""
									class="h-full w-full object-cover"
								/>
							{:else}
								<div class="dark:text-text-muted-dark flex h-full items-center justify-center text-xs text-text-muted">
									No preview
								</div>
							{/if}
							<div class="absolute right-1 top-1">
								<span
									class={`inline-block rounded-sm px-1.5 py-0.5 text-[10px] font-medium ${
										sample.distill_status === 'completed'
											? 'bg-emerald-500/90 text-white'
											: sample.distill_status === 'failed'
												? 'bg-red-500/90 text-white'
												: sample.distill_status === 'skipped'
													? 'bg-gray-500/80 text-white'
													: 'bg-amber-500/90 text-white'
									}`}
								>
									{sample.distill_status === 'completed'
										? `${sample.distill_detections ?? sample.detection_bbox_count ?? 0} det`
										: sample.distill_status}
								</span>
							</div>
							{#if sample.retest_count > 0}
								<div class="absolute bottom-1 right-1">
									<span class="inline-block rounded-sm bg-violet-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white">
										{sample.retest_count} retest{sample.retest_count === 1 ? '' : 's'}
									</span>
								</div>
							{/if}
						</div>
						<div class="px-2 py-1.5">
							<div class="flex items-baseline justify-between gap-1">
								<span class="dark:text-text-dark truncate text-xs font-medium text-text">
									{scopeLabel(sample.detection_scope) || scopeLabel(sample.source_role ?? sample.camera)}
								</span>
								<span class="dark:text-text-muted-dark shrink-0 text-[10px] text-text-muted">
									{timeAgo(sample.captured_at)}
								</span>
							</div>
							<div class="dark:text-text-muted-dark mt-0.5 truncate text-[10px] text-text-muted">
								{modelShort(sample.detection_openrouter_model) || sample.detection_algorithm || ''}
							</div>
						</div>
					</a>
				{/each}
			</div>
		{/if}
	</div>
</div>
