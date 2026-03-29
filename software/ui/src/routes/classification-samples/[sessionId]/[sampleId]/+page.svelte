<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type RetestModelOption = {
		id: string;
		label: string;
	};

	type RetestSummary = {
		retest_id: string;
		created_at: number | null;
		model: string;
		found: boolean;
		bbox?: [number, number, number, number] | null;
		candidate_bboxes?: [number, number, number, number][];
		bbox_count: number;
		score?: number | null;
		error?: string | null;
		overlay_image_url?: string | null;
		result_json_url?: string | null;
	};

	type LiveRetestState = 'running' | 'completed' | 'error';

	type LiveRetestCard = {
		local_id: string;
		run_token: string;
		model: string;
		status: LiveRetestState;
		requested_at: number;
		retest?: RetestSummary | null;
		error?: string | null;
	};

	type RetestCard = {
		key: string;
		model: string;
		status: LiveRetestState;
		created_at: number | null;
		found: boolean | null;
		bbox?: [number, number, number, number] | null;
		bbox_count: number | null;
		score?: number | null;
		error?: string | null;
		overlay_image_url?: string | null;
		result_json_url?: string | null;
	};

	type SampleDetail = {
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
		detection_found?: boolean | null;
		detection_bbox?: [number, number, number, number] | null;
		detection_candidate_bboxes?: [number, number, number, number][];
		detection_bbox_count?: number | null;
		detection_score?: number | null;
		detection_message?: string | null;
		distill_status: string;
		distill_detections?: number | null;
		input_image_url?: string | null;
		top_zone_url?: string | null;
		bottom_zone_url?: string | null;
		top_frame_url?: string | null;
		bottom_frame_url?: string | null;
		distill_error?: string | null;
		distill_result?: {
			detections: number;
			overlay_image_url?: string | null;
			result_json_url?: string | null;
			yolo_label_url?: string | null;
			processed_at?: number | null;
		} | null;
		retests: RetestSummary[];
	};

	const manager = getMachinesContext();

	let loadedKey = $state('');
	let loading = $state(false);
	let deleting = $state(false);
	let retesting = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let sample = $state<SampleDetail | null>(null);
	let availableRetestModels = $state<RetestModelOption[]>([]);
	let retestModel = $state('google/gemini-3-flash-preview');
	let liveRetests = $state<LiveRetestCard[]>([]);
	let activeRetestCount = $state(0);

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

	function bboxSummary(bbox: [number, number, number, number] | null | undefined): string {
		if (!bbox) return 'n/a';
		return `${Math.max(0, bbox[2] - bbox[0])} x ${Math.max(0, bbox[3] - bbox[1])}`;
	}

	function modelLabel(model: string | null | undefined): string {
		if (typeof model !== 'string' || !model) return 'n/a';
		return availableRetestModels.find((option) => option.id === model)?.label ?? model;
	}

	function sourceLabel(source: string | null | undefined): string {
		if (typeof source !== 'string' || !source) return 'n/a';
		return source
			.split('_')
			.map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
			.join(' ');
	}

	async function loadSample(): Promise<boolean> {
		loading = true;
		errorMsg = null;
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}`
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			sample = (payload?.sample ?? null) as SampleDetail | null;
			availableRetestModels = Array.isArray(payload?.available_retest_models)
				? payload.available_retest_models.filter(
						(value: any): value is RetestModelOption =>
							typeof value?.id === 'string' && typeof value?.label === 'string'
				  )
				: Array.isArray(payload?.available_openrouter_models)
					? payload.available_openrouter_models.filter(
							(value: any): value is RetestModelOption =>
								typeof value?.id === 'string' && typeof value?.label === 'string'
					  )
					: [];
			if (
				availableRetestModels.length > 0 &&
				!availableRetestModels.some((option) => option.id === retestModel)
			) {
				retestModel = availableRetestModels[0].id;
			}
			return true;
		} catch (error: unknown) {
			sample = null;
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to load the classification sample.';
			return false;
		} finally {
			loading = false;
		}
	}

	function updateLiveRetest(
		localId: string,
		mutate: (entry: LiveRetestCard) => LiveRetestCard
	) {
		liveRetests = liveRetests.map((entry) => (entry.local_id === localId ? mutate(entry) : entry));
	}

	function removeLiveRetestsForRun(runToken: string, predicate?: (entry: LiveRetestCard) => boolean) {
		liveRetests = liveRetests.filter(
			(entry) => entry.run_token !== runToken || (predicate ? !predicate(entry) : false)
		);
	}

	function displayedRetestCards(): RetestCard[] {
		const liveCards = liveRetests.map((entry) => {
			const retest = entry.retest;
			return {
				key: entry.local_id,
				model: retest?.model ?? entry.model,
				status: entry.status,
				created_at: retest?.created_at ?? entry.requested_at,
				found: retest?.found ?? null,
				bbox: retest?.bbox ?? null,
				bbox_count:
					typeof retest?.bbox_count === 'number'
						? retest.bbox_count
						: entry.status === 'running'
							? null
							: 0,
				score: retest?.score ?? null,
				error: entry.status === 'error' ? (entry.error ?? retest?.error ?? null) : (retest?.error ?? null),
				overlay_image_url: retest?.overlay_image_url ?? null,
				result_json_url: retest?.result_json_url ?? null
			};
		});
		const savedCards = (sample?.retests ?? []).map((retest) => ({
			key: `saved:${retest.retest_id}`,
			model: retest.model,
			status: 'completed' as const,
			created_at: retest.created_at,
			found: retest.found,
			bbox: retest.bbox ?? null,
			bbox_count: retest.bbox_count,
			score: retest.score ?? null,
			error: retest.error ?? null,
			overlay_image_url: retest.overlay_image_url ?? null,
			result_json_url: retest.result_json_url ?? null
		}));
		return [...liveCards, ...savedCards];
	}

	async function runRetestRequest(model: string, runToken: string, index: number): Promise<boolean> {
		const requestedAt = Date.now() / 1000;
		const localId = `${runToken}:${index}:${model}`;
		liveRetests = [
			...liveRetests,
			{
				local_id: localId,
				run_token: runToken,
				model,
				status: 'running',
				requested_at: requestedAt,
				retest: null,
				error: null
			}
		];

		const sessionId = page.params.sessionId;
		const sampleId = page.params.sampleId;
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}/retest`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ model_id: model })
				}
			);
			if (!res.ok) {
				throw new Error(await res.text());
			}
			const payload = await res.json();
			const retest = (payload?.retest ?? null) as RetestSummary | null;
			updateLiveRetest(localId, (entry) => ({
				...entry,
				status: 'completed',
				retest,
				error: null
			}));
			return true;
		} catch (error: unknown) {
			updateLiveRetest(localId, (entry) => ({
				...entry,
				status: 'error',
				error:
					error instanceof Error && error.message
						? error.message
						: 'Retest failed.',
				retest: null
			}));
			return false;
		}
	}

	async function runRetests(models: string[], completionMessage: (succeeded: number, failed: number) => string) {
		retesting = true;
		activeRetestCount = models.length;
		errorMsg = null;
		statusMsg =
			models.length === 1
				? `Running ${modelLabel(models[0])}...`
				: `Running ${models.length} models in parallel...`;
		const runToken = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
		try {
			const results = await Promise.all(
				models.map(async (model, index) => {
					const succeeded = await runRetestRequest(model, runToken, index);
					activeRetestCount = Math.max(0, activeRetestCount - 1);
					return succeeded;
				})
			);
			const succeeded = results.filter(Boolean).length;
			const failed = results.length - succeeded;
			statusMsg = completionMessage(succeeded, failed);
			const synced = await loadSample();
			if (synced) {
				removeLiveRetestsForRun(runToken, (entry) => entry.status === 'completed');
			}
		} finally {
			retesting = false;
			activeRetestCount = 0;
		}
	}

	async function runRetest() {
		await runRetests([retestModel], (succeeded, failed) =>
			failed === 0
				? 'Retest completed and saved to the sample history.'
				: `Retest finished with ${succeeded} success and ${failed} error.`
		);
	}

	async function runAllRetests() {
		await runRetests(
			availableRetestModels.map((option) => option.id),
			(succeeded, failed) =>
				failed === 0
					? `Completed ${succeeded} retests and saved them to the sample history.`
					: `Completed ${succeeded} retests with ${failed} error${failed === 1 ? '' : 's'}.`
		);
	}

	async function deleteSample() {
		if (!sample || deleting || retesting) return;
		if (
			typeof window !== 'undefined' &&
			!window.confirm(`Delete sample ${sample.sample_id}? This also removes its saved assets and retests.`)
		) {
			return;
		}

		deleting = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const sessionId = page.params.sessionId;
			const sampleId = page.params.sampleId;
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/classification/training/sessions/${sessionId}/samples/${sampleId}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			await goto('/classification-samples');
		} catch (error: unknown) {
			errorMsg =
				error instanceof Error && error.message
					? error.message
					: 'Failed to delete the sample.';
		} finally {
			deleting = false;
		}
	}

	$effect(() => {
		const routeKey = `${page.params.sessionId}/${page.params.sampleId}/${
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__'
		}`;
		if (routeKey !== loadedKey) {
			loadedKey = routeKey;
			void loadSample();
		}
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<AppHeader />

	<div class="flex flex-col gap-6">
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div>
				<a
					href="/classification-samples"
					class="text-sm text-sky-600 transition-colors hover:text-sky-500 dark:text-sky-300"
				>
					← Back to library
				</a>
				<h2 class="dark:text-text-dark mt-2 text-2xl font-semibold text-text">
					{sample?.sample_id ?? 'Classification Sample'}
				</h2>
				<p class="dark:text-text-muted-dark mt-1 text-sm text-text-muted">
					{sample?.session_name ?? 'Loading session...'}
				</p>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				<button
					type="button"
					onclick={loadSample}
					disabled={loading || deleting}
					class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Loading...' : 'Reload'}
				</button>
				<button
					type="button"
					onclick={deleteSample}
					disabled={!sample || loading || deleting || retesting}
					class="border border-red-500 bg-red-500/10 px-3 py-2 text-sm text-red-700 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-300"
				>
					{deleting ? 'Deleting...' : 'Delete Sample'}
				</button>
			</div>
		</div>

		{#if errorMsg}
			<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
				{errorMsg}
			</div>
		{:else if statusMsg}
			<div class="border border-emerald-400 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-300">
				{statusMsg}
			</div>
		{/if}

		{#if sample}
			<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
				<div class="flex flex-col gap-6">
					<div class="grid gap-4 lg:grid-cols-2">
						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="dark:text-text-dark mb-3 text-sm font-semibold text-text">Saved Raw Crop</div>
							<div class="dark:bg-bg-dark aspect-[4/3] bg-bg">
								{#if assetUrl(sample.input_image_url)}
									<img
										src={assetUrl(sample.input_image_url) ?? undefined}
										alt={`Raw sample ${sample.sample_id}`}
										class="h-full w-full object-contain"
									/>
								{/if}
							</div>
						</div>

						<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
							<div class="dark:text-text-dark mb-3 text-sm font-semibold text-text">Distilled Overlay</div>
							<div class="dark:bg-bg-dark aspect-[4/3] bg-bg">
								{#if assetUrl(sample.distill_result?.overlay_image_url)}
									<img
										src={assetUrl(sample.distill_result?.overlay_image_url) ?? undefined}
										alt={`Distilled overlay ${sample.sample_id}`}
										class="h-full w-full object-contain"
									/>
								{:else}
									<div class="dark:text-text-muted-dark flex h-full items-center justify-center text-sm text-text-muted">
										No distilled overlay yet
									</div>
								{/if}
							</div>
						</div>
					</div>

					{#if sample.bottom_frame_url}
						<div class="grid gap-4 lg:grid-cols-2">
							{#if assetUrl(sample.bottom_frame_url)}
								<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
									<div class="dark:text-text-dark mb-3 text-sm font-semibold text-text">Bottom Full Frame</div>
									<div class="dark:bg-bg-dark aspect-[4/3] bg-bg">
										<img src={assetUrl(sample.bottom_frame_url) ?? undefined} alt="Bottom full frame" class="h-full w-full object-contain" />
									</div>
								</div>
							{/if}
						</div>
					{/if}

					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
						<div class="flex items-center justify-between gap-3">
							<div>
								<div class="dark:text-text-dark text-sm font-semibold text-text">Retest With Another Model</div>
								<div class="dark:text-text-muted-dark mt-1 text-xs text-text-muted">
									Run one model or the full comparison set on the saved raw crop, including local detector runs.
								</div>
							</div>
						</div>
						<div class="mt-4 flex flex-col gap-3 lg:flex-row lg:items-end">
							<label class="dark:text-text-dark min-w-0 flex-1 text-xs text-text">
								Retest Model
								<select
									value={retestModel}
									onchange={(event) => (retestModel = event.currentTarget.value)}
									disabled={retesting}
									class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-2 text-sm text-text"
								>
									{#each availableRetestModels as option}
										<option value={option.id}>{option.label}</option>
									{/each}
								</select>
							</label>
							<button
								type="button"
								onclick={runRetest}
								disabled={retesting || availableRetestModels.length === 0}
								class="border border-sky-500 bg-sky-500/15 px-3 py-2 text-sm text-sky-700 transition-colors hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-sky-300"
							>
								{retesting ? 'Running...' : 'Run Selected'}
							</button>
							<button
								type="button"
								onclick={runAllRetests}
								disabled={retesting || availableRetestModels.length === 0}
								class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
							>
								{retesting ? 'Running...' : `Run All Models (${availableRetestModels.length})`}
							</button>
						</div>

						{#if retesting && activeRetestCount > 0}
							<div class="dark:text-text-muted-dark mt-3 text-xs text-text-muted">
								{activeRetestCount} retest{activeRetestCount === 1 ? '' : 's'} still running...
							</div>
						{/if}

						<div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
							{#if displayedRetestCards().length === 0}
								<div class="dark:text-text-muted-dark text-sm text-text-muted md:col-span-2 xl:col-span-3">
									No retests saved yet.
								</div>
							{:else}
								{#each displayedRetestCards() as retest (retest.key)}
									<article class="dark:border-border-dark dark:bg-bg-dark overflow-hidden border border-border bg-bg">
										<div class="dark:bg-surface-dark aspect-[4/3] bg-surface">
											{#if retest.status === 'running'}
												<div class="flex h-full flex-col items-center justify-center gap-3">
													<div class="h-10 w-10 animate-spin rounded-full border-4 border-sky-500/20 border-t-sky-500"></div>
													<div class="text-sm text-sky-600 dark:text-sky-300">Running...</div>
												</div>
											{:else if assetUrl(retest.overlay_image_url)}
												<img
													src={assetUrl(retest.overlay_image_url) ?? undefined}
													alt={`Retest ${retest.key}`}
													class="h-full w-full object-contain"
												/>
											{:else}
												<div class="dark:text-text-muted-dark flex h-full items-center justify-center text-sm text-text-muted">
													{retest.status === 'error' ? 'Retest failed' : 'No overlay saved'}
												</div>
											{/if}
										</div>
										<div class="px-2.5 py-2">
											<div class="flex items-baseline justify-between gap-2">
												<div class="dark:text-text-dark text-sm font-semibold text-text">{modelLabel(retest.model)}</div>
												{#if retest.status === 'running'}
													<span class="text-[11px] font-medium text-sky-600 dark:text-sky-300">Running</span>
												{:else if retest.status === 'error'}
													<span class="text-[11px] font-medium text-red-600 dark:text-red-400">Error</span>
												{:else}
													<span class="text-[11px] font-medium text-emerald-700 dark:text-emerald-300">Saved</span>
												{/if}
											</div>
											<div class="dark:text-text-muted-dark mt-0.5 flex items-center gap-3 text-[11px] text-text-muted">
												<span>{formatDate(retest.created_at)}</span>
												<span>{retest.found === null ? '' : retest.found ? `${retest.bbox_count} det` : 'No det'}{typeof retest.score === 'number' ? ` / ${retest.score.toFixed(2)}` : ''}</span>
												{#if retest.bbox}<span>{bboxSummary(retest.bbox)}</span>{/if}
											</div>
											<div class="dark:text-text-muted-dark mt-0.5 flex items-center gap-2 font-mono text-[10px] text-text-muted">
												<span>{retest.model}</span>
												{#if retest.status !== 'running' && assetUrl(retest.result_json_url)}
													<a
														href={assetUrl(retest.result_json_url) ?? undefined}
														target="_blank"
														rel="noreferrer"
														class="text-sky-600 hover:text-sky-500 dark:text-sky-300"
													>JSON</a>
												{/if}
											</div>
											{#if retest.error}
												<div class="mt-1 text-[11px] text-red-600 dark:text-red-400">{retest.error}</div>
											{/if}
										</div>
									</article>
								{/each}
							{/if}
						</div>
					</div>
				</div>

				<div class="flex flex-col gap-4">
					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
						<div class="dark:text-text-dark text-sm font-semibold text-text">Sample Meta</div>
						<div class="mt-3 grid gap-3 text-sm">
							<div>
								<div class="dark:text-text-muted-dark text-xs text-text-muted">Captured</div>
								<div class="dark:text-text-dark mt-1 text-text">{formatDate(sample.captured_at)}</div>
							</div>
							<div>
								<div class="dark:text-text-muted-dark text-xs text-text-muted">Source</div>
								<div class="dark:text-text-dark mt-1 text-text">{sourceLabel(sample.source)}</div>
							</div>
							{#if sample.detection_scope}
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Scope</div>
									<div class="dark:text-text-dark mt-1 text-text">{sourceLabel(sample.detection_scope)}</div>
								</div>
							{/if}
							<div>
								<div class="dark:text-text-muted-dark text-xs text-text-muted">Camera</div>
								<div class="dark:text-text-dark mt-1 text-text">
									{sourceLabel(sample.source_role ?? sample.preferred_camera ?? sample.camera ?? 'n/a')}
								</div>
							</div>
							{#if sample.capture_reason}
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Capture Reason</div>
									<div class="dark:text-text-dark mt-1 text-text">{sourceLabel(sample.capture_reason)}</div>
								</div>
							{/if}
							<div>
								<div class="dark:text-text-muted-dark text-xs text-text-muted">Processor</div>
								<div class="dark:text-text-dark mt-1 text-text">{sample.processor}</div>
							</div>
							{#if sample.detection_algorithm}
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Capture Detection</div>
									<div class="dark:text-text-dark mt-1 text-text">{sample.detection_algorithm}</div>
								</div>
							{/if}
							{#if sample.detection_openrouter_model}
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Capture Model</div>
									<div class="dark:text-text-dark mt-1 text-text">
										{modelLabel(sample.detection_openrouter_model)}
									</div>
								</div>
							{/if}
							{#if sample.detection_bbox_count !== undefined && sample.detection_bbox_count !== null}
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Captured Detections</div>
									<div class="dark:text-text-dark mt-1 text-text">{sample.detection_bbox_count}</div>
								</div>
							{/if}
							<div>
								<div class="dark:text-text-muted-dark text-xs text-text-muted">Distill Status</div>
								<div class="dark:text-text-dark mt-1 text-text">{sample.distill_status}</div>
							</div>
						</div>
					</div>

					<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-4">
						<div class="dark:text-text-dark text-sm font-semibold text-text">Distillation</div>
						{#if sample.distill_result}
							<div class="mt-3 grid gap-3 text-sm">
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Detections</div>
									<div class="dark:text-text-dark mt-1 text-text">{sample.distill_result.detections}</div>
								</div>
								<div>
									<div class="dark:text-text-muted-dark text-xs text-text-muted">Processed</div>
									<div class="dark:text-text-dark mt-1 text-text">
										{formatDate(sample.distill_result.processed_at)}
									</div>
								</div>
								{#if assetUrl(sample.distill_result.result_json_url)}
									<a
										href={assetUrl(sample.distill_result.result_json_url) ?? undefined}
										target="_blank"
										rel="noreferrer"
										class="text-sm text-sky-600 hover:text-sky-500 dark:text-sky-300"
									>
										Open result JSON
									</a>
								{/if}
								{#if assetUrl(sample.distill_result.yolo_label_url)}
									<a
										href={assetUrl(sample.distill_result.yolo_label_url) ?? undefined}
										target="_blank"
										rel="noreferrer"
										class="text-sm text-sky-600 hover:text-sky-500 dark:text-sky-300"
									>
										Open YOLO label
									</a>
								{/if}
							</div>
						{:else if sample.distill_error}
							<div class="mt-3 text-sm text-red-600 dark:text-red-400">{sample.distill_error}</div>
						{:else if sample.distill_status === 'skipped'}
							<div class="dark:text-text-muted-dark mt-3 text-sm text-text-muted">
								Distillation was intentionally skipped for this sample source. You can still retest the saved crop with any available model.
							</div>
						{:else}
							<div class="dark:text-text-muted-dark mt-3 text-sm text-text-muted">
								No distillation result saved yet.
							</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
