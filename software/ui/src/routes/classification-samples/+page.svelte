<script lang="ts">
	import { onMount } from 'svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

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
	let selectedRole = $state<string>('all');
	let selectedAlgorithm = $state<string>('all');
	let selectedModel = $state<string>('all');
	let selectedStatus = $state<string>('all');

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

	function formatDate(timestamp: number | null | undefined): string {
		if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) {
			return 'n/a';
		}
		return new Date(timestamp * 1000).toLocaleString();
	}

	function sourceLabel(source: string | null | undefined): string {
		if (typeof source !== 'string' || !source) return 'n/a';
		return source
			.split('_')
			.map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
			.join(' ');
	}

	function titleCase(value: string | null | undefined): string {
		if (typeof value !== 'string' || !value) return 'n/a';
		return value
			.split('_')
			.map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
			.join(' ');
	}

	function modelLabel(model: string | null | undefined): string {
		if (typeof model !== 'string' || !model) return 'n/a';
		const compact = model.split('/').pop() ?? model;
		return compact.length > 28 ? `${compact.slice(0, 28)}...` : compact;
	}

	function filterOptions(values: Array<string | null | undefined>): string[] {
		return [...new Set(values.filter((value): value is string => typeof value === 'string' && !!value))].sort();
	}

	function visibleSamples(): SampleSummary[] {
		return samples.filter((sample) => {
			if (selectedSessionId !== 'all' && sample.session_id !== selectedSessionId) return false;
			if (selectedScope !== 'all' && (sample.detection_scope ?? 'unknown') !== selectedScope) return false;
			if (selectedRole !== 'all' && (sample.source_role ?? sample.camera ?? 'unknown') !== selectedRole) return false;
			if (
				selectedAlgorithm !== 'all' &&
				(sample.detection_algorithm ?? 'unknown') !== selectedAlgorithm
			) {
				return false;
			}
			if (
				selectedModel !== 'all' &&
				(sample.detection_openrouter_model ?? 'unknown') !== selectedModel
			) {
				return false;
			}
			if (selectedStatus !== 'all' && sample.distill_status !== selectedStatus) return false;
			return true;
		});
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
			if (selectedSessionId !== 'all' && !sessions.some((session) => session.session_id === selectedSessionId)) {
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

	<div class="flex flex-col gap-6">
		<div class="flex flex-wrap items-end justify-between gap-3">
			<div>
				<h2 class="dark:text-text-dark text-2xl font-semibold text-text">Classification Samples</h2>
				<p class="dark:text-text-muted-dark mt-1 max-w-3xl text-sm text-text-muted">
					Saved detection samples from chamber, C-channels, and carousel views for later review, distillation, and model-vs-model retests.
				</p>
			</div>
			<button
				type="button"
				onclick={loadLibrary}
				disabled={loading}
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				{loading ? 'Loading...' : 'Reload'}
			</button>
		</div>

		{#if errorMsg}
			<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
				{errorMsg}
			</div>
		{/if}

		<div class="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
			<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
				<div class="dark:text-text-dark text-sm font-semibold text-text">Sessions</div>
				<div class="mt-3 flex flex-col gap-2">
					<button
						type="button"
						onclick={() => (selectedSessionId = 'all')}
						class={`w-full border px-3 py-2 text-left text-sm transition-colors ${
							selectedSessionId === 'all'
								? 'border-sky-500 bg-sky-500/10 text-sky-700 dark:text-sky-300'
								: 'dark:border-border-dark dark:text-text-dark dark:hover:bg-bg-dark border-border text-text hover:bg-bg'
						}`}
					>
						<div class="font-medium">All Sessions</div>
						<div class="dark:text-text-muted-dark mt-1 text-xs text-text-muted">
							{samples.length} samples total
						</div>
					</button>

					{#each sessions as session}
						<button
							type="button"
							onclick={() => (selectedSessionId = session.session_id)}
							class={`w-full border px-3 py-2 text-left text-sm transition-colors ${
								selectedSessionId === session.session_id
									? 'border-sky-500 bg-sky-500/10 text-sky-700 dark:text-sky-300'
									: 'dark:border-border-dark dark:text-text-dark dark:hover:bg-bg-dark border-border text-text hover:bg-bg'
							}`}
						>
							<div class="font-medium">{session.session_name}</div>
							<div class="dark:text-text-muted-dark mt-1 text-xs text-text-muted">
								{session.sample_count} samples
							</div>
							<div class="dark:text-text-muted-dark mt-1 text-[11px] text-text-muted">
								Started {formatDate(session.created_at)}
							</div>
						</button>
					{/each}
				</div>
			</div>

			<div class="flex flex-col gap-4">
				<div class="grid gap-3 sm:grid-cols-3">
					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface px-4 py-3">
						<div class="dark:text-text-muted-dark text-xs uppercase tracking-[0.14em] text-text-muted">Samples</div>
						<div class="dark:text-text-dark mt-1 text-2xl font-semibold text-text">{visibleSamples().length}</div>
					</div>
					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface px-4 py-3">
						<div class="dark:text-text-muted-dark text-xs uppercase tracking-[0.14em] text-text-muted">Sessions</div>
						<div class="dark:text-text-dark mt-1 text-2xl font-semibold text-text">{sessions.length}</div>
					</div>
					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface px-4 py-3">
						<div class="dark:text-text-muted-dark text-xs uppercase tracking-[0.14em] text-text-muted">Ready</div>
						<div class="dark:text-text-dark mt-1 text-2xl font-semibold text-text">
							{visibleSamples().filter((sample) => sample.distill_status === 'completed').length}
						</div>
					</div>
				</div>

				<div class="dark:border-border-dark dark:bg-surface-dark grid gap-3 border border-border bg-surface p-4 md:grid-cols-3 xl:grid-cols-6">
					<label class="dark:text-text-dark text-xs text-text">
						Scope
						<select
							value={selectedScope}
							onchange={(event) => (selectedScope = event.currentTarget.value)}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All scopes</option>
							{#each filterOptions(samples.map((sample) => sample.detection_scope)) as scope}
								<option value={scope}>{titleCase(scope)}</option>
							{/each}
						</select>
					</label>
					<label class="dark:text-text-dark text-xs text-text">
						Role
						<select
							value={selectedRole}
							onchange={(event) => (selectedRole = event.currentTarget.value)}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All roles</option>
							{#each filterOptions(samples.map((sample) => sample.source_role ?? sample.camera)) as role}
								<option value={role}>{titleCase(role)}</option>
							{/each}
						</select>
					</label>
					<label class="dark:text-text-dark text-xs text-text">
						Algorithm
						<select
							value={selectedAlgorithm}
							onchange={(event) => (selectedAlgorithm = event.currentTarget.value)}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All algorithms</option>
							{#each filterOptions(samples.map((sample) => sample.detection_algorithm)) as detectionAlgorithm}
								<option value={detectionAlgorithm}>{titleCase(detectionAlgorithm)}</option>
							{/each}
						</select>
					</label>
					<label class="dark:text-text-dark text-xs text-text">
						Model
						<select
							value={selectedModel}
							onchange={(event) => (selectedModel = event.currentTarget.value)}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All models</option>
							{#each filterOptions(samples.map((sample) => sample.detection_openrouter_model)) as model}
								<option value={model}>{modelLabel(model)}</option>
							{/each}
						</select>
					</label>
					<label class="dark:text-text-dark text-xs text-text">
						Distill
						<select
							value={selectedStatus}
							onchange={(event) => (selectedStatus = event.currentTarget.value)}
							class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-2 text-sm text-text"
						>
							<option value="all">All statuses</option>
							{#each filterOptions(samples.map((sample) => sample.distill_status)) as status}
								<option value={status}>{titleCase(status)}</option>
							{/each}
						</select>
					</label>
					<div class="dark:border-border-dark dark:bg-bg-dark flex items-end border border-border bg-bg px-3 py-2 text-xs text-text-muted dark:text-text-muted-dark">
						{visibleSamples().length} matching sample{visibleSamples().length === 1 ? '' : 's'}
					</div>
				</div>

				{#if !loading && visibleSamples().length === 0}
					<div class="dark:border-border-dark dark:bg-surface-dark dark:text-text-muted-dark border border-dashed border-border bg-surface px-4 py-5 text-sm text-text-muted">
						No saved samples match the current filters. Run a detection test or enable positive sample collection on a live station to build the library.
					</div>
				{:else}
					<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
						{#each visibleSamples() as sample}
							<a
								href={sample.detail_url ?? '#'}
								class="dark:border-border-dark dark:bg-surface-dark overflow-hidden border border-border bg-surface transition-colors hover:border-sky-500/60"
							>
								<div class="dark:bg-bg-dark aspect-[4/3] bg-bg">
									{#if assetUrl(sample.input_image_url)}
										<img
											src={assetUrl(sample.input_image_url) ?? undefined}
											alt={`Sample ${sample.sample_id}`}
											class="h-full w-full object-contain"
										/>
									{:else}
										<div class="dark:text-text-muted-dark flex h-full items-center justify-center text-sm text-text-muted">
											No preview
										</div>
									{/if}
								</div>
								<div class="flex flex-col gap-2 px-4 py-3">
									<div class="flex items-center justify-between gap-2">
										<div class="dark:text-text-dark min-w-0 truncate text-sm font-semibold text-text">
											{sample.sample_id}
										</div>
										<div
											class={`shrink-0 text-[11px] uppercase tracking-[0.12em] ${
												sample.distill_status === 'completed'
													? 'text-emerald-600 dark:text-emerald-300'
													: sample.distill_status === 'failed'
														? 'text-red-600 dark:text-red-400'
														: 'text-amber-600 dark:text-amber-300'
											}`}
										>
											{sample.distill_status}
										</div>
									</div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">
										{sample.session_name}
									</div>
									<div class="flex flex-wrap gap-1 text-[11px]">
										<span class="dark:bg-bg-dark dark:text-text-dark rounded border border-border bg-bg px-2 py-1 text-text">
											{titleCase(sample.detection_scope ?? 'unknown')}
										</span>
										<span class="dark:bg-bg-dark dark:text-text-dark rounded border border-border bg-bg px-2 py-1 text-text">
											{titleCase(sample.source_role ?? sample.camera ?? 'unknown')}
										</span>
										{#if sample.detection_algorithm}
											<span class="dark:bg-bg-dark dark:text-text-dark rounded border border-border bg-bg px-2 py-1 text-text">
												{titleCase(sample.detection_algorithm)}
											</span>
										{/if}
									</div>
									<div class="grid grid-cols-2 gap-2 text-xs">
										<div class="dark:text-text-muted-dark text-text-muted">
											<div>Source</div>
											<div class="dark:text-text-dark mt-1 font-medium text-text">
												{sourceLabel(sample.source)}
											</div>
										</div>
										<div class="dark:text-text-muted-dark text-text-muted">
											<div>Camera</div>
											<div class="dark:text-text-dark mt-1 font-medium text-text">
												{titleCase(sample.source_role ?? sample.preferred_camera ?? sample.camera ?? 'n/a')}
											</div>
										</div>
										<div class="dark:text-text-muted-dark text-text-muted">
											<div>Detections</div>
											<div class="dark:text-text-dark mt-1 font-medium text-text">
												{sample.detection_bbox_count ?? sample.distill_detections ?? 0}
											</div>
										</div>
										<div class="dark:text-text-muted-dark text-text-muted">
											<div>Retests</div>
											<div class="dark:text-text-dark mt-1 font-medium text-text">{sample.retest_count}</div>
										</div>
										{#if sample.detection_openrouter_model}
											<div class="dark:text-text-muted-dark col-span-2 text-text-muted">
												<div>Capture Model</div>
												<div class="dark:text-text-dark mt-1 font-medium text-text">
													{modelLabel(sample.detection_openrouter_model)}
												</div>
											</div>
										{/if}
									</div>
									<div class="dark:text-text-muted-dark text-[11px] text-text-muted">
										{formatDate(sample.captured_at)}
									</div>
								</div>
							</a>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
