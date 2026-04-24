<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { Bug, Camera, Search, X } from 'lucide-svelte';

	const manager = getMachinesContext();

	type CameraCaptureResult = {
		available: boolean;
		captured_frames: number;
		resolution?: [number, number];
		error?: string;
	};

	type DetectionScope = 'classification' | 'feeder' | 'carousel' | 'classification_channel';
	type DetectionCamera =
		| 'top'
		| 'bottom'
		| 'c_channel_2'
		| 'c_channel_3'
		| 'carousel'
		| 'classification_channel';
	type DetectionAlgorithm = string;
	type DetectionAlgorithmOption = {
		id: DetectionAlgorithm;
		label: string;
		needs_baseline: boolean;
		description?: string;
	};
	type OpenRouterModelOption = {
		id: string;
		label: string;
	};
	type DetectionDebugResult = {
		found: boolean;
		algorithm: DetectionAlgorithm;
		message: string;
		score?: number | null;
		bbox?: [number, number, number, number] | null;
		normalized_bbox?: [number, number, number, number] | null;
		candidate_bboxes?: [number, number, number, number][];
		candidate_previews?: (string | null)[];
		normalized_candidate_bboxes?: [number, number, number, number][];
		zone_bbox?: [number, number, number, number] | null;
		frame_resolution?: [number, number];
		bbox_count?: number;
		zone_point_count?: number;
		saved_to_library?: boolean;
		saved_sample_error?: string | null;
	};

	let {
		scope = 'classification',
		camera,
		label,
		hasCamera = true,
		onClose,
		onDetectionHighlightChange
	}: {
		scope?: DetectionScope;
		camera: DetectionCamera;
		label: string;
		hasCamera?: boolean;
		onClose?: (() => void) | undefined;
		onDetectionHighlightChange?:
			| ((bboxes: [number, number, number, number][]) => void)
			| undefined;
	} = $props();

	let loadedMachineKey = $state('');
	let loadedConfigKey = $state('');
	let loadedCameraKey = $state('');
	let loadingConfig = $state(false);
	let savingConfig = $state(false);
	let capturing = $state(false);
	let testing = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let captureResult = $state<Record<string, CameraCaptureResult> | null>(null);
	let debugResult = $state<DetectionDebugResult | null>(null);
	let algorithm = $state<DetectionAlgorithm>('baseline_diff');
	let availableAlgorithms = $state<DetectionAlgorithmOption[]>([]);
	let openrouterModel = $state('google/gemini-3-flash-preview');
	let availableOpenrouterModels = $state<OpenRouterModelOption[]>([]);
	let sampleCollectionEnabled = $state(true);
	let sampleCollectionSupported = $state(true);

	async function extractErrorMessage(res: Response): Promise<string> {
		const text = await res.text();
		try {
			const json = JSON.parse(text);
			if (typeof json?.detail === 'string') return json.detail;
		} catch {}
		return text;
	}

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function configPath(): string {
		if (scope === 'feeder') return `/api/feeder/detection-config?role=${encodeURIComponent(camera)}`;
		if (scope === 'classification_channel') return '/api/classification-channel/detection-config';
		if (scope === 'carousel') return '/api/carousel/detection-config';
		return '/api/classification/detection-config';
	}

	function defaultAlgorithmForScope(currentScope: DetectionScope): DetectionAlgorithm {
		if (currentScope === 'feeder') return 'mog2';
		if (currentScope === 'carousel' || currentScope === 'classification_channel') return 'heatmap_diff';
		return 'baseline_diff';
	}

	function testPath(): string {
		if (scope === 'feeder') return `/api/feeder/detect/${camera}`;
		if (scope === 'classification_channel') return '/api/classification-channel/detect/current';
		if (scope === 'carousel') return '/api/carousel/detect/current';
		return `/api/classification/detect/${camera}`;
	}

	function baselineCapturePath(): string | null {
		if (scope === 'classification') return '/api/classification/baseline/capture';
		if (scope === 'classification_channel')
			return '/api/classification-channel/detection/baseline/capture';
		if (scope === 'carousel') return '/api/carousel/detection/baseline/capture';
		return null;
	}

	function scopeTitle(): string {
		if (scope === 'feeder') return 'C-Channel Tools';
		if (scope === 'classification_channel') return 'Classification C-Channel (C4) Tools';
		if (scope === 'carousel') return 'Carousel Tools';
		return 'Chamber Tools';
	}

	function scopeDescription(): string {
		if (scope === 'feeder') {
			return `Compare detection methods on the live ${label} frame and optionally archive periodic positive samples from rt perception.`;
		}
		if (scope === 'classification_channel') {
			return 'Compare C4 trigger methods on the live classification-channel frame and optionally archive periodic positive samples from rt perception.';
		}
		if (scope === 'carousel') {
			return 'Compare carousel trigger methods on the live handoff frame and optionally archive positive samples for later training.';
		}
		return `Compare detection methods on the live ${label} frame and save chamber samples for later review and retesting.`;
	}

	function baselineButtonLabel(): string {
		if (scope === 'carousel' || scope === 'classification_channel') return 'Capture Current Baseline';
		return 'Capture Empty Baseline';
	}

	function resultFoundLabel(found: boolean): string {
		return found ? 'Object found' : 'No object';
	}

	function resetTransientState() {
		errorMsg = null;
		statusMsg = '';
		captureResult = null;
		debugResult = null;
		onDetectionHighlightChange?.([]);
	}

	function applyDebugResult(payload: DetectionDebugResult | null) {
		debugResult = payload;
		onDetectionHighlightChange?.(
			payload?.normalized_candidate_bboxes?.length
				? payload.normalized_candidate_bboxes
				: payload?.normalized_bbox
					? [payload.normalized_bbox]
					: []
		);
	}

	async function loadConfig() {
		loadingConfig = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${configPath()}`);
			if (!res.ok) throw new Error(await extractErrorMessage(res));
			const payload = await res.json();
			if (typeof payload?.algorithm === 'string') {
				algorithm = payload.algorithm as DetectionAlgorithm;
			}
			if (typeof payload?.openrouter_model === 'string') {
				openrouterModel = payload.openrouter_model;
			}
			sampleCollectionEnabled =
				scope === 'classification'
					? false
					: typeof payload?.sample_collection_enabled === 'boolean'
						? payload.sample_collection_enabled
						: false;
			sampleCollectionSupported =
				scope === 'classification'
					? false
					: typeof payload?.sample_collection_supported === 'boolean'
						? payload.sample_collection_supported
						: false;
			availableAlgorithms = Array.isArray(payload?.available_algorithms)
				? payload.available_algorithms.filter(
						(value: any): value is DetectionAlgorithmOption =>
							typeof value?.id === 'string' &&
							typeof value?.label === 'string' &&
							typeof value?.needs_baseline === 'boolean'
				 )
				: [];
			availableOpenrouterModels = Array.isArray(payload?.available_openrouter_models)
				? payload.available_openrouter_models.filter(
						(value: any): value is OpenRouterModelOption =>
							typeof value?.id === 'string' && typeof value?.label === 'string'
				 )
				: [];
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load detection settings.';
		} finally {
			loadingConfig = false;
		}
	}

	function configBody(nextAlgorithm = algorithm, nextModel = openrouterModel, nextSampleCollection = sampleCollectionEnabled) {
		const body: Record<string, unknown> = {
			algorithm: nextAlgorithm,
			openrouter_model: nextModel
		};
		if (scope !== 'classification') {
			body.sample_collection_enabled = nextSampleCollection;
		}
		return body;
	}

	async function persistConfig(
		nextAlgorithm = algorithm,
		nextModel = openrouterModel,
		nextSampleCollection = sampleCollectionEnabled,
		fallbackMessage = 'Detection settings updated.',
		preferFallbackMessage = false
	) {
		savingConfig = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${configPath()}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(configBody(nextAlgorithm, nextModel, nextSampleCollection))
			});
			if (!res.ok) throw new Error(await extractErrorMessage(res));
			const payload = await res.json();
			algorithm = nextAlgorithm;
			openrouterModel =
				typeof payload?.openrouter_model === 'string' ? payload.openrouter_model : nextModel;
			if (scope !== 'classification') {
				sampleCollectionEnabled =
					typeof payload?.sample_collection_enabled === 'boolean'
						? payload.sample_collection_enabled
						: nextSampleCollection;
				sampleCollectionSupported =
					typeof payload?.sample_collection_supported === 'boolean'
						? payload.sample_collection_supported
						: sampleCollectionSupported;
			}
			applyDebugResult(null);
			captureResult = null;
			const backendMessage =
				typeof payload?.message === 'string' && payload.message ? payload.message : null;
			const sampleCollectionSupportNote =
				backendMessage?.includes(
					'Periodic sample collection is only available with split feeder cameras.'
				)
					? 'Periodic sample collection is only available with split feeder cameras.'
					: null;
			statusMsg = preferFallbackMessage
				? `${fallbackMessage}${sampleCollectionSupportNote ? ` ${sampleCollectionSupportNote}` : ''}`
				: (backendMessage ?? fallbackMessage);
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to update detection settings.';
		} finally {
			savingConfig = false;
		}
	}

	async function saveAlgorithm(value: string) {
		if (!availableAlgorithms.some((option) => option.id === value)) return;
		await persistConfig(value as DetectionAlgorithm, openrouterModel, sampleCollectionEnabled);
	}

	async function saveOpenRouterModel(value: string) {
		if (!availableOpenrouterModels.some((option) => option.id === value)) return;
		await persistConfig(
			algorithm,
			value,
			sampleCollectionEnabled,
			'OpenRouter model updated.',
			true
		);
	}

	async function saveSampleCollection(value: boolean) {
		await persistConfig(
			algorithm,
			openrouterModel,
			value,
			value
				? 'Periodic positive sample collection enabled.'
				: 'Periodic positive sample collection disabled.',
			true
		);
	}

	async function captureBaseline() {
		const path = baselineCapturePath();
		if (!path) return;
		capturing = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${path}`, { method: 'POST' });
			if (!res.ok) throw new Error(await extractErrorMessage(res));
			const payload = await res.json();
			captureResult =
				payload?.cameras && typeof payload.cameras === 'object'
					? (payload.cameras as Record<string, CameraCaptureResult>)
					: null;
			applyDebugResult(null);
			statusMsg = payload?.message ?? 'Baseline captured.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to capture a fresh baseline.';
		} finally {
			capturing = false;
		}
	}

	async function testCurrentFrame() {
		testing = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${testPath()}`, { method: 'POST' });
			if (!res.ok) throw new Error(await extractErrorMessage(res));
			const payload = (await res.json()) as DetectionDebugResult;
			applyDebugResult(payload);
			statusMsg = payload.message;
			if (payload.saved_to_library) {
				statusMsg = `${payload.message} Archived locally for reference.`;
			} else if (payload.saved_sample_error) {
				statusMsg = `${payload.message} Could not archive this test run: ${payload.saved_sample_error}`;
			}
		} catch (e: any) {
			applyDebugResult(null);
			errorMsg = e.message ?? 'Failed to test detection.';
		} finally {
			testing = false;
		}
	}

	function closeSidebar() {
		resetTransientState();
		onClose?.();
	}

	function bboxSummary(bbox: [number, number, number, number] | null | undefined): string {
		if (!bbox) return 'n/a';
		const width = Math.max(0, bbox[2] - bbox[0]);
		const height = Math.max(0, bbox[3] - bbox[1]);
		return `${width} x ${height}`;
	}

	function resultToneClass(found: boolean): string {
		return found
			? 'font-semibold text-success dark:text-emerald-300'
			: 'font-semibold text-amber-700 dark:text-amber-300';
	}

	function selectedAlgorithmOption(): DetectionAlgorithmOption | null {
		return availableAlgorithms.find((option) => option.id === algorithm) ?? null;
	}

	function algorithmSummary(): string {
		if (loadingConfig) return `Loading ${scopeTitle().toLowerCase()} settings...`;
		if (savingConfig) return `Saving ${scopeTitle().toLowerCase()} settings...`;
		return (
			selectedAlgorithmOption()?.description ??
			'Uses the selected detection path for live previews, settings tests, and archived samples.'
		);
	}

	function algorithmShortLabel(value: DetectionAlgorithm): string {
		return availableAlgorithms.find((candidate) => candidate.id === value)?.label ?? value;
	}

	function openRouterModelShortLabel(value: string): string {
		return availableOpenrouterModels.find((candidate) => candidate.id === value)?.label ?? value;
	}

	function showSampleCollectionToggle(): boolean {
		return scope !== 'classification' && sampleCollectionSupported;
	}

	function sampleCollectionDescription(): string {
		if (!sampleCollectionSupported) {
			return 'Periodic positive sample collection is unavailable for the current camera setup.';
		}
		if (scope === 'feeder') {
			return `Every few seconds, archive detected ${label} candidates as cropped local training samples with the full frame attached as context.`;
		}
		if (scope === 'classification_channel') {
			return 'Every few seconds, archive detected C4 candidates as cropped local training samples with the full frame attached as context.';
		}
		if (scope === 'carousel') {
			return 'Archive positive carousel samples for later filtering, retesting, and model-training backfill.';
		}
		return 'Save live positive samples from this scope for later filtering and retesting.';
	}

	function canCaptureBaseline(): boolean {
		return !!baselineCapturePath() && !!selectedAlgorithmOption()?.needs_baseline;
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		const configKey =
			scope === 'feeder' ? `${machineKey}:${scope}:${camera}` : `${machineKey}:${scope}`;
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
		}
		if (configKey !== loadedConfigKey) {
			loadedConfigKey = configKey;
			algorithm = defaultAlgorithmForScope(scope);
			resetTransientState();
			void loadConfig();
		}
	});

	$effect(() => {
		if (loadedCameraKey !== `${scope}:${camera}`) {
			loadedCameraKey = `${scope}:${camera}`;
			resetTransientState();
		}
	});
</script>

<aside
	class="flex h-full min-w-0 flex-col border border-border bg-bg xl:min-h-[32rem]"
>
	<div
		class="border-b border-border bg-surface px-4 py-3"
	>
		<div class="flex items-start justify-between gap-3">
			<div class="flex items-start gap-3">
				<div
					class="flex h-9 w-9 items-center justify-center rounded-full bg-bg text-text"
				>
					<Bug size={16} />
				</div>
				<div class="min-w-0">
					<div class="text-sm font-semibold text-text">{scopeTitle()}</div>
					<div class="mt-0.5 text-xs text-text-muted">
						{scopeDescription()}
					</div>
				</div>
			</div>
			{#if onClose}
				<button
					onclick={closeSidebar}
					class="inline-flex h-8 w-8 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-bg hover:text-text"
					aria-label="Close detection debug"
				>
					<X size={15} />
				</button>
			{/if}
		</div>
	</div>

	<div class="flex flex-1 flex-col gap-3 px-4 py-4">
		{#if !hasCamera}
			<div
				class="border border-dashed border-border bg-surface px-3 py-2 text-xs text-text-muted"
			>
				Assign a camera to {label} before testing detection on the live feed.
			</div>
		{/if}

		{#if errorMsg}
			<div class="border border-danger bg-danger/10 px-3 py-2 text-sm text-danger dark:border-danger dark:bg-danger/10 dark:text-red-400">
				{errorMsg}
			</div>
		{/if}

		<div class="grid grid-cols-1 gap-3">
			<div class="grid gap-3 border border-border bg-surface px-3 py-3">
				<label class="text-xs text-text">
					Detection Method
					<select
						value={algorithm}
						onchange={(event) => void saveAlgorithm(event.currentTarget.value)}
						disabled={loadingConfig || savingConfig || capturing || testing}
						class="mt-1 w-full border border-border bg-surface px-2 py-2 text-sm text-text"
					>
						{#each availableAlgorithms as option}
							<option value={option.id}>{option.label}</option>
						{/each}
					</select>
				</label>

				{#if algorithm === 'gemini_sam'}
					<label class="text-xs text-text">
						OpenRouter Model
						<select
							value={openrouterModel}
							onchange={(event) => void saveOpenRouterModel(event.currentTarget.value)}
							disabled={loadingConfig || savingConfig || capturing || testing}
							class="mt-1 w-full border border-border bg-surface px-2 py-2 text-sm text-text"
						>
							{#each availableOpenrouterModels as option}
								<option value={option.id}>{option.label}</option>
							{/each}
						</select>
						<div class="mt-1 text-sm text-text-muted">
							{openRouterModelShortLabel(openrouterModel)}
						</div>
					</label>
				{/if}

				{#if showSampleCollectionToggle()}
					<label class="flex items-start gap-3 border border-border bg-bg px-3 py-2.5 text-xs text-text">
						<input
							type="checkbox"
							checked={sampleCollectionEnabled}
							onchange={(event) => void saveSampleCollection(event.currentTarget.checked)}
							disabled={
								loadingConfig ||
								savingConfig ||
								capturing ||
								testing ||
								!sampleCollectionSupported
							}
							class="mt-0.5 h-4 w-4 accent-sky-500"
						/>
						<span class="min-w-0">
							<span class="block text-sm font-medium text-text">
								Collect Positive Samples
							</span>
							<span class="mt-0.5 block text-xs text-text-muted">
								{sampleCollectionDescription()}
							</span>
						</span>
					</label>
				{:else if scope !== 'classification'}
					<div class="border border-border bg-bg px-3 py-2.5 text-xs text-text-muted">
						{sampleCollectionDescription()}
					</div>
				{/if}

				<div class="border border-border bg-bg px-3 py-2 text-xs leading-5 text-text-muted">
					{algorithmSummary()}
				</div>

				<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
					<button
						type="button"
						onclick={testCurrentFrame}
						disabled={!hasCamera || loadingConfig || savingConfig || capturing || testing}
						class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-sky-500 bg-sky-500/15 px-3 py-2 text-sm text-sky-700 transition-colors hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-50 dark:text-sky-300"
					>
						<Search size={15} />
						<span>{testing ? 'Testing...' : 'Test Current Frame'}</span>
					</button>

					{#if canCaptureBaseline()}
						<button
							type="button"
							onclick={captureBaseline}
							disabled={capturing || savingConfig || loadingConfig || testing}
							class="inline-flex w-full cursor-pointer items-center justify-center gap-2 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
						>
							<Camera size={15} />
							<span>{capturing ? 'Capturing...' : baselineButtonLabel()}</span>
						</button>
					{/if}
				</div>

				{#if debugResult}
					<div class="grid grid-cols-2 gap-1.5 text-xs">
						<div class="border border-border bg-bg px-2.5 py-2">
							<div class="text-text-muted">Result</div>
							<div class={resultToneClass(debugResult.found)}>
								{resultFoundLabel(debugResult.found)}
							</div>
						</div>
						<div class="border border-border bg-bg px-2.5 py-2">
							<div class="text-text-muted">Algorithm</div>
							<div class="font-mono text-sm text-text">
								{algorithmShortLabel(debugResult.algorithm)}
							</div>
						</div>
						<div class="border border-border bg-bg px-2.5 py-2">
							<div class="text-text-muted">Best Box</div>
							<div class="font-mono text-sm text-text">
								{bboxSummary(debugResult.bbox)}
							</div>
						</div>
						<div class="border border-border bg-bg px-2.5 py-2">
							<div class="text-text-muted">
								{debugResult.score === undefined || debugResult.score === null ? 'Zone Pts' : 'Score'}
							</div>
							<div class="font-mono text-sm text-text">
								{#if debugResult.score !== undefined && debugResult.score !== null}
									{debugResult.score.toFixed(1)}
								{:else}
									{debugResult.zone_point_count ?? 0}
								{/if}
							</div>
						</div>
						<div class="border border-border bg-bg px-2.5 py-2">
							<div class="text-text-muted">Frame</div>
							<div class="font-mono text-sm text-text">
								{#if debugResult.frame_resolution}
									{debugResult.frame_resolution[0]} x {debugResult.frame_resolution[1]}
								{:else}
									n/a
								{/if}
							</div>
						</div>
						<div class="border border-border bg-bg px-2.5 py-2">
							<div class="text-text-muted">
								{debugResult.bbox_count === undefined ? 'Zone Box' : 'Candidates'}
							</div>
							<div class="font-mono text-sm text-text">
								{#if debugResult.bbox_count !== undefined}
									{debugResult.bbox_count}
								{:else}
									{bboxSummary(debugResult.zone_bbox)}
								{/if}
							</div>
						</div>
					</div>

					{#if debugResult.candidate_bboxes && debugResult.candidate_bboxes.length > 0}
						<div class="grid gap-2 border border-border bg-bg px-3 py-3">
							<div class="text-xs uppercase tracking-[0.14em] text-text-muted">
								Candidate Boxes
							</div>
							<div class="grid grid-cols-2 gap-1.5 text-xs">
								{#each debugResult.candidate_bboxes.slice(0, 6) as bbox, index}
									<div class="grid gap-2 border border-border px-2.5 py-2">
										{#if debugResult.candidate_previews?.[index]}
											<div class="flex aspect-square items-center justify-center overflow-hidden border border-border bg-surface">
												<img
													src={`data:image/jpeg;base64,${debugResult.candidate_previews[index]}`}
													alt={`Candidate ${index + 1}`}
													class="h-full w-full object-contain"
												/>
											</div>
										{/if}
										<div class="font-medium text-text">#{index + 1}</div>
										<div class="font-mono text-text-muted">
											{bboxSummary(bbox)}
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				{/if}

				{#if captureResult}
					<div class="grid grid-cols-1 gap-2 border border-border bg-bg px-3 py-3">
						<div class="text-xs uppercase tracking-[0.14em] text-text-muted">
							Baseline Capture
						</div>
						<div class="grid grid-cols-2 gap-2 text-xs">
							{#each Object.entries(captureResult) as [name, cameraResult]}
								<div class="border border-border px-2.5 py-2">
									<div class="font-medium capitalize text-text">{name}</div>
									<div class="mt-1 text-text-muted">
										{#if !cameraResult.available}
											Not configured
										{:else if cameraResult.error}
											{cameraResult.error}
										{:else}
											{cameraResult.captured_frames} frames{#if cameraResult.resolution}
												{' '}at {cameraResult.resolution[0]}x{cameraResult.resolution[1]}
											{/if}
										{/if}
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if statusMsg}
					<div class="text-sm text-text-muted">{statusMsg}</div>
				{/if}
			</div>
		</div>
	</div>
</aside>
