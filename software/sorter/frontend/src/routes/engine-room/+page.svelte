<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import type { KnownObjectData } from '$lib/api/events';

	type StatusTone = 'ok' | 'warn' | 'err' | 'idle' | 'info';

	type CameraRole =
		| 'feeder'
		| 'c_channel_2'
		| 'c_channel_3'
		| 'carousel'
		| 'classification_channel'
		| 'classification_top'
		| 'classification_bottom';

	type CaptureModeInfo = {
		current?: { width?: number | null; height?: number | null; fps?: number | null; fourcc?: string | null } | null;
		live?: { width?: number; height?: number; fps?: number | null } | null;
	};

	type HiveInstalledModel = {
		local_id?: string;
		model_id?: string;
		name?: string;
		variant_runtime?: string;
		size_bytes?: number;
	};

	type ServoStatus = {
		bus_online?: boolean;
		layers?: { layer_index: number; available: boolean; name?: string }[];
	};

	type BinsLayout = {
		layers?: {
			layer_index: number;
			enabled: boolean;
			section_count: number;
			bin_count: number;
		}[];
	};

	type CameraConfig = Record<string, unknown>;

	type FeederDetectionConfig = {
		algorithm?: string | null;
		algorithm_by_role?: Record<string, string | null> | null;
		openrouter_model?: string | null;
	};

	type AuxDetectionConfig = {
		algorithm?: string | null;
		openrouter_model?: string | null;
		scope?: string | null;
	};

	type RuntimePreferences = {
		preferences?: Record<string, string>;
	};

	type RuntimeCapabilities = {
		cpu?: { name?: string };
		coreml?: { available?: boolean; device?: string };
		ncnn?: { available?: boolean; vulkan_available?: boolean; devices?: string[] };
		onnxruntime?: { available?: boolean; providers?: string[] };
		hailo?: { available?: boolean };
		tensorrt?: { available?: boolean };
	} & Record<string, unknown>;

	type TrackedPieceRow = {
		uuid: string;
		piece: KnownObjectData;
		live: boolean;
		active: boolean;
	};

	type StateMachineSnapshot = {
		current_state?: string;
		entered_at?: number;
	};

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	// ---------------------------------------------------------------------------
	// State (fetched or pulled from machine context)
	// ---------------------------------------------------------------------------

	let cameraConfig = $state<CameraConfig | null>(null);
	let captureModes = $state<Record<string, CaptureModeInfo | null>>({});
	let feederDetection = $state<FeederDetectionConfig | null>(null);
	let auxDetection = $state<AuxDetectionConfig | null>(null);
	let installedModels = $state<HiveInstalledModel[]>([]);
	let runtimePrefs = $state<RuntimePreferences | null>(null);
	let runtimeCaps = $state<RuntimeCapabilities | null>(null);
	let servoStatus = $state<ServoStatus | null>(null);
	let binsLayout = $state<BinsLayout | null>(null);
	let trackedRows = $state<TrackedPieceRow[]>([]);
	let nowTs = $state<number>(Date.now() / 1000);

	// Live data from WebSocket-fed machine context
	const cameraHealth = $derived(ctx.machine?.cameraHealth ?? new Map<string, string>());
	const runtimeStats = $derived(ctx.machine?.runtimeStats ?? null);
	const systemStatus = $derived(ctx.machine?.systemStatus ?? null);
	const sorterState = $derived(ctx.machine?.sorterState ?? null);

	// Per-camera last frame timestamps (seconds) — derived from machine frames
	const lastFrameAtByRole = $derived.by(() => {
		const map = new Map<string, number>();
		const frames = ctx.machine?.frames;
		if (!frames) return map;
		for (const [role, frame] of frames.entries()) {
			if (frame?.timestamp) map.set(role, frame.timestamp);
		}
		return map;
	});

	// ---------------------------------------------------------------------------
	// Roles ordering
	// ---------------------------------------------------------------------------

	const FEEDER_CHANNEL_ROLES: { role: CameraRole; short: string; name: string }[] = [
		{ role: 'c_channel_2', short: 'C2', name: 'C-Channel 2' },
		{ role: 'c_channel_3', short: 'C3', name: 'C-Channel 3' }
	];

	const AUX_ROLE = $derived(
		(cameraConfig && typeof cameraConfig === 'object' &&
			('carousel' in cameraConfig || 'classification_channel' in cameraConfig))
			? ('classification_channel' in cameraConfig && cameraConfig.classification_channel != null
				? 'classification_channel'
				: 'carousel')
			: 'carousel'
	);

	type PipelineCamera = {
		role: CameraRole;
		short: string;
		name: string;
	};

	const ALL_CAMERA_ROLES = $derived<PipelineCamera[]>([
		...FEEDER_CHANNEL_ROLES,
		{ role: AUX_ROLE as CameraRole, short: AUX_ROLE === 'classification_channel' ? 'CCh' : 'C4', name: AUX_ROLE === 'classification_channel' ? 'Classification Channel' : 'Carousel' },
		{ role: 'classification_top', short: 'CT', name: 'Classification Top' },
		{ role: 'classification_bottom', short: 'CB', name: 'Classification Bottom' }
	]);

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatSecondsAgo(ts: number | null | undefined): string {
		if (!ts || !Number.isFinite(ts)) return '—';
		const diff = Math.max(0, nowTs - ts);
		if (diff < 1) return `${(diff * 1000).toFixed(0)}ms ago`;
		if (diff < 60) return `${diff.toFixed(1)}s ago`;
		if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
		return `${Math.round(diff / 3600)}h ago`;
	}

	function formatDuration(seconds: number | null | undefined): string {
		if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '—';
		if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const mins = Math.floor(seconds / 60);
		const rem = Math.floor(seconds % 60);
		return `${mins}m ${rem}s`;
	}

	function cameraHealthFor(role: string): string {
		return cameraHealth.get(role) ?? 'unknown';
	}

	function cameraTone(status: string): StatusTone {
		if (status === 'online') return 'ok';
		if (status === 'reconnecting' || status === 'degraded') return 'warn';
		if (status === 'offline' || status === 'error') return 'err';
		return 'idle';
	}

	function hardwareTone(state: string | undefined): StatusTone {
		if (state === 'ready') return 'ok';
		if (state === 'homing' || state === 'initializing' || state === 'initialized') return 'info';
		if (state === 'error') return 'err';
		if (state === 'standby') return 'warn';
		return 'idle';
	}

	function runtimeTone(state: string | undefined): StatusTone {
		if (state === 'running') return 'ok';
		if (state === 'paused') return 'warn';
		if (state === 'initializing') return 'info';
		return 'idle';
	}

	function toneDotClass(tone: StatusTone): string {
		if (tone === 'ok') return 'bg-success';
		if (tone === 'warn') return 'bg-warning';
		if (tone === 'err') return 'bg-danger';
		if (tone === 'info') return 'bg-info';
		return 'bg-text-muted/50';
	}

	function toneFlowClass(tone: StatusTone): string {
		if (tone === 'ok') return 'border-success text-success';
		if (tone === 'warn') return 'border-warning text-warning';
		if (tone === 'err') return 'border-danger text-danger';
		if (tone === 'info') return 'border-info text-info';
		return 'border-border text-text-muted';
	}

	function resolveAlgorithmForRole(role: CameraRole): string {
		if (role === 'c_channel_2' || role === 'c_channel_3') {
			const byRole = feederDetection?.algorithm_by_role ?? null;
			if (byRole && byRole[role]) return String(byRole[role]);
			return feederDetection?.algorithm ?? '—';
		}
		if (role === 'carousel' || role === 'classification_channel') {
			return auxDetection?.algorithm ?? '—';
		}
		return '—';
	}

	function inferenceDeviceForAlgorithm(algorithm: string): string | null {
		if (!algorithm) return null;
		// Match heuristically: "ncnn" → check ncnn prefs; "onnx" → onnx prefs; etc.
		const lower = algorithm.toLowerCase();
		if (lower.includes('openrouter') || lower.includes('gemini') || lower.includes('llm')) return 'Cloud';
		if (lower.includes('brickognize')) return 'Cloud';
		if (lower.includes('diff') || lower.includes('motion')) return 'CPU';
		const prefs = runtimePrefs?.preferences ?? {};
		if (lower.includes('ncnn') && prefs.ncnn) return prefs.ncnn;
		if (lower.includes('coreml') && prefs.coreml) return prefs.coreml;
		if (lower.includes('onnx') && prefs.onnx) return prefs.onnx;
		if (lower.includes('hailo')) return 'Hailo';
		if (lower.includes('tensorrt')) return 'TensorRT';
		// Fall back to the first preference
		const first = Object.values(prefs)[0];
		return typeof first === 'string' ? first : null;
	}

	function hiveModelFor(algorithm: string): HiveInstalledModel | null {
		if (!algorithm) return null;
		// Look for a model whose local_id matches any token in the algorithm name.
		for (const model of installedModels) {
			const id = (model.local_id || model.model_id || '').toString();
			if (!id) continue;
			if (algorithm.toLowerCase().includes(id.toLowerCase())) return model;
		}
		return null;
	}

	function trackedForRole(role: CameraRole): TrackedPieceRow[] {
		if (trackedRows.length === 0) return [];
		const isFeeder = role === 'c_channel_2' || role === 'c_channel_3' || role === 'carousel' || role === 'classification_channel';
		if (!isFeeder) return [];
		// trackedRows don't expose a role directly; we approximate by lifecycle stage.
		if (role === 'c_channel_2' || role === 'c_channel_3') {
			return trackedRows.filter((row) => row.active && !row.piece.carousel_detected_confirmed_at);
		}
		return trackedRows.filter((row) => row.active && !!row.piece.carousel_detected_confirmed_at && row.piece.stage !== 'distributed');
	}

	// ---------------------------------------------------------------------------
	// State-machine extraction from runtime stats
	// ---------------------------------------------------------------------------

	function getStateMachine(name: string): StateMachineSnapshot | null {
		const raw = runtimeStats as Record<string, unknown> | null;
		if (!raw) return null;
		const block = raw.state_machines;
		if (!block || typeof block !== 'object') return null;
		const entry = (block as Record<string, unknown>)[name];
		if (!entry || typeof entry !== 'object') return null;
		return entry as StateMachineSnapshot;
	}

	const feederSM = $derived(getStateMachine('feeder.ch3') ?? getStateMachine('feeder.ch2') ?? getStateMachine('feeder.ch1'));
	const classificationSM = $derived(getStateMachine('classification.occupancy'));
	const distributionSM = $derived(getStateMachine('distribution.occupancy'));

	const pipelineRows = $derived([
		{ name: 'Feeder', sm: feederSM, key: 'feeder' as const },
		{ name: 'Classification', sm: classificationSM, key: 'classification' as const },
		{ name: 'Distribution', sm: distributionSM, key: 'distribution' as const }
	]);

	const servoBusOnline = $derived(servoStatus?.bus_online ?? false);
	const servoLayers = $derived(servoStatus?.layers ?? []);
	const servoLayersAvailable = $derived(servoLayers.filter((l) => l.available).length);

	const binLayers = $derived(binsLayout?.layers ?? []);
	const binLayersEnabled = $derived(binLayers.filter((l) => l.enabled).length);
	const binTotalBins = $derived(binLayers.reduce((sum, l) => sum + (l.bin_count ?? 0), 0));
	const binTotalSections = $derived(binLayers.reduce((sum, l) => sum + (l.section_count ?? 0), 0));

	function stateMachineTone(sm: StateMachineSnapshot | null): StatusTone {
		if (!sm) return 'idle';
		const s = (sm.current_state ?? '').toLowerCase();
		if (!s || s === 'idle' || s === 'empty' || s === 'ready') return 'idle';
		if (s.includes('error') || s.includes('fail') || s.includes('lost')) return 'err';
		if (s.includes('wait') || s.includes('pending')) return 'warn';
		return 'ok';
	}

	// ---------------------------------------------------------------------------
	// Counts
	// ---------------------------------------------------------------------------

	const runtimeCounts = $derived.by(() => {
		const raw = runtimeStats as Record<string, unknown> | null;
		if (!raw) return null;
		const c = raw.counts;
		if (!c || typeof c !== 'object') return null;
		return c as Record<string, number>;
	});

	const lifecycleState = $derived.by(() => {
		const raw = runtimeStats as Record<string, unknown> | null;
		const value = raw?.lifecycle_state;
		return typeof value === 'string' ? value : null;
	});

	const hardwareState = $derived(systemStatus?.hardware_state ?? 'standby');
	const hardwareError = $derived(systemStatus?.hardware_error ?? null);
	const machineState = $derived(sorterState?.state ?? 'initializing');

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	async function safeFetch<T>(path: string): Promise<T | null> {
		try {
			const res = await fetch(`${effectiveBase()}${path}`);
			if (!res.ok) return null;
			return (await res.json()) as T;
		} catch {
			return null;
		}
	}

	async function refreshHighChurn() {
		const tracked = await safeFetch<{ items?: TrackedPieceRow[] }>('/api/tracked/pieces?limit=200');
		if (tracked) trackedRows = Array.isArray(tracked.items) ? tracked.items : [];
	}

	async function refreshCaptureModes() {
		const rolesToFetch: CameraRole[] = [
			'c_channel_2',
			'c_channel_3',
			AUX_ROLE as CameraRole,
			'classification_top',
			'classification_bottom'
		];
		const pairs = await Promise.all(
			rolesToFetch.map(async (role) => {
				const mode = await safeFetch<CaptureModeInfo>(`/api/cameras/capture-modes/${role}`);
				return [role, mode] as const;
			})
		);
		const next: Record<string, CaptureModeInfo | null> = { ...captureModes };
		for (const [role, mode] of pairs) next[role] = mode;
		captureModes = next;
	}

	async function refreshStatic() {
		const [cfg, feeder, aux, models, prefs, caps, servo, bins] = await Promise.all([
			safeFetch<CameraConfig>('/api/cameras/config'),
			safeFetch<FeederDetectionConfig>('/api/feeder/detection-config'),
			safeFetch<AuxDetectionConfig>('/api/classification-channel/detection-config').then((x) => x ?? safeFetch<AuxDetectionConfig>('/api/carousel/detection-config')),
			safeFetch<{ items?: HiveInstalledModel[] }>('/api/hive/models/installed'),
			safeFetch<RuntimePreferences>('/api/runtimes/preferences'),
			safeFetch<RuntimeCapabilities>('/api/runtimes/capabilities'),
			safeFetch<ServoStatus>('/api/hardware/servo-status'),
			safeFetch<BinsLayout>('/api/bins/layout')
		]);
		if (cfg) cameraConfig = cfg;
		if (feeder) feederDetection = feeder;
		if (aux) auxDetection = aux;
		if (models) installedModels = Array.isArray(models.items) ? models.items : [];
		if (prefs) runtimePrefs = prefs;
		if (caps) runtimeCaps = caps;
		if (servo) servoStatus = servo;
		if (bins) binsLayout = bins;
	}

	// ---------------------------------------------------------------------------
	// Polling lifecycle
	// ---------------------------------------------------------------------------

	let tickTimer: ReturnType<typeof setInterval> | null = null;
	let highChurnTimer: ReturnType<typeof setInterval> | null = null;
	let captureTimer: ReturnType<typeof setInterval> | null = null;
	let staticTimer: ReturnType<typeof setInterval> | null = null;

	onMount(() => {
		// clock ticker (1s) — drives "last frame Xs ago" relative labels
		tickTimer = setInterval(() => {
			nowTs = Date.now() / 1000;
		}, 1000);

		// high-churn (1s): tracked pieces (system status + sorter state + runtime stats
		// already arrive via WebSocket into the machine context, no need to refetch)
		void refreshHighChurn();
		highChurnTimer = setInterval(() => void refreshHighChurn(), 1000);

		// camera capture modes (2s)
		void refreshCaptureModes();
		captureTimer = setInterval(() => void refreshCaptureModes(), 2000);

		// static config (10s)
		void refreshStatic();
		staticTimer = setInterval(() => void refreshStatic(), 10000);
	});

	onDestroy(() => {
		if (tickTimer) clearInterval(tickTimer);
		if (highChurnTimer) clearInterval(highChurnTimer);
		if (captureTimer) clearInterval(captureTimer);
		if (staticTimer) clearInterval(staticTimer);
	});

	// ---------------------------------------------------------------------------
	// Layout math for SVG arrow connectors between rows
	// ---------------------------------------------------------------------------

	const ROW_IDS = ['cameras', 'detection', 'trackers', 'pipeline', 'hardware'] as const;
	type RowId = typeof ROW_IDS[number];

	function rowTone(row: RowId): StatusTone {
		if (row === 'cameras') {
			if (cameraHealth.size === 0) return 'idle';
			const vals = Array.from(cameraHealth.values());
			const onlineCount = vals.filter((v) => v === 'online').length;
			if (onlineCount === vals.length) return 'ok';
			if (onlineCount === 0) return 'err';
			return 'warn';
		}
		if (row === 'detection') {
			return feederDetection || auxDetection ? 'ok' : 'idle';
		}
		if (row === 'trackers') {
			return trackedRows.length > 0 ? 'ok' : 'idle';
		}
		if (row === 'pipeline') {
			if (machineState === 'running') return 'ok';
			if (machineState === 'paused') return 'warn';
			return 'idle';
		}
		if (row === 'hardware') {
			if (hardwareState === 'ready') return 'ok';
			if (hardwareState === 'error') return 'err';
			if (hardwareState === 'homing' || hardwareState === 'initializing') return 'info';
			return 'warn';
		}
		return 'idle';
	}
</script>

<svelte:head><title>Engine Room · Sorter</title></svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />

	<div class="px-4 py-5 sm:px-6">
		<div class="mb-5 flex items-end justify-between gap-4">
			<div>
				<h1 class="text-xl font-bold font-mono uppercase tracking-tight text-text">Engine Room</h1>
				<p class="mt-1 text-sm text-text-muted">
					Live block diagram of the sorter's runtime architecture — cameras → detection → tracking → pipeline → hardware.
				</p>
			</div>
			<div class="flex items-center gap-3 text-sm text-text-muted">
				<span class="inline-flex items-center gap-1.5">
					<span class="inline-block h-2 w-2 {toneDotClass(runtimeTone(machineState))}"></span>
					Runtime: <span class="font-mono text-text">{machineState}</span>
				</span>
				<span class="inline-flex items-center gap-1.5">
					<span class="inline-block h-2 w-2 {toneDotClass(hardwareTone(hardwareState))}"></span>
					Hardware: <span class="font-mono text-text">{hardwareState}</span>
				</span>
				{#if lifecycleState}
					<span class="inline-flex items-center gap-1.5">
						Lifecycle: <span class="font-mono text-text">{lifecycleState}</span>
					</span>
				{/if}
			</div>
		</div>

		<!-- Block diagram -->
		<div class="flex flex-col gap-0">

			<!-- ROW: CAMERAS -->
			<section class="engine-row">
				<div class="engine-row-label">
					<div class="engine-row-title">Cameras</div>
					<div class="text-xs text-text-muted">{cameraHealth.size} assigned</div>
				</div>
				<div class="engine-row-cards">
					{#each ALL_CAMERA_ROLES as cam (cam.role)}
						{@const status = cameraHealthFor(cam.role)}
						{@const tone = cameraTone(status)}
						{@const mode = captureModes[cam.role]}
						{@const live = mode?.live ?? null}
						{@const saved = mode?.current ?? null}
						{@const lastTs = lastFrameAtByRole.get(cam.role)}
						<div class="engine-card">
							<div class="engine-card-head">
								<span class="engine-dot {toneDotClass(tone)}"></span>
								<div class="engine-card-title">{cam.name}</div>
								<div class="engine-card-subtitle">{cam.short}</div>
							</div>
							<div class="engine-card-body">
								<div class="engine-stat">
									<div class="engine-stat-label">Status</div>
									<div class="engine-stat-value">{status}</div>
								</div>
								<div class="engine-stat">
									<div class="engine-stat-label">Capture</div>
									<div class="engine-stat-value font-mono">
										{#if live?.width && live?.height}
											{live.width}×{live.height}{#if live.fps} @ {live.fps}fps{/if}
										{:else if saved?.width && saved?.height}
											{saved.width}×{saved.height}{#if saved.fps} @ {saved.fps}fps{/if}{#if saved.fourcc} {saved.fourcc}{/if}
										{:else}
											—
										{/if}
									</div>
								</div>
								<div class="engine-stat">
									<div class="engine-stat-label">Last frame</div>
									<div class="engine-stat-value font-mono">{formatSecondsAgo(lastTs)}</div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			</section>

			<div class="engine-arrow" class:engine-arrow-active={rowTone('cameras') === 'ok' && rowTone('detection') === 'ok'}></div>

			<!-- ROW: DETECTION -->
			<section class="engine-row">
				<div class="engine-row-label">
					<div class="engine-row-title">Detection</div>
					<div class="text-xs text-text-muted">{installedModels.length} hive model{installedModels.length === 1 ? '' : 's'}</div>
				</div>
				<div class="engine-row-cards">
					{#each ALL_CAMERA_ROLES as cam (cam.role)}
						{@const algorithm = resolveAlgorithmForRole(cam.role)}
						{@const hive = hiveModelFor(algorithm)}
						{@const device = inferenceDeviceForAlgorithm(algorithm)}
						{@const tone = algorithm && algorithm !== '—' ? 'ok' : 'idle'}
						<div class="engine-card">
							<div class="engine-card-head">
								<span class="engine-dot {toneDotClass(tone)}"></span>
								<div class="engine-card-title">{cam.short}</div>
								<div class="engine-card-subtitle truncate" title={algorithm}>{algorithm}</div>
							</div>
							<div class="engine-card-body">
								{#if hive}
									<div class="engine-stat">
										<div class="engine-stat-label">Model</div>
										<div class="engine-stat-value font-mono truncate" title={hive.name ?? hive.local_id ?? ''}>
											{hive.name ?? hive.local_id ?? '—'}
										</div>
									</div>
									<div class="engine-stat">
										<div class="engine-stat-label">Runtime</div>
										<div class="engine-stat-value font-mono">{hive.variant_runtime ?? '—'}</div>
									</div>
								{:else if cam.role === 'classification_top' || cam.role === 'classification_bottom'}
									<div class="engine-stat">
										<div class="engine-stat-label">Role</div>
										<div class="engine-stat-value">Brickognize crop</div>
									</div>
								{:else}
									<div class="engine-stat">
										<div class="engine-stat-label">Model</div>
										<div class="engine-stat-value text-text-muted">—</div>
									</div>
								{/if}
								<div class="engine-stat">
									<div class="engine-stat-label">Device</div>
									<div class="engine-stat-value font-mono">{device ?? '—'}</div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			</section>

			<div class="engine-arrow" class:engine-arrow-active={rowTone('detection') === 'ok' && rowTone('trackers') === 'ok'}></div>

			<!-- ROW: TRACKERS -->
			<section class="engine-row">
				<div class="engine-row-label">
					<div class="engine-row-title">Trackers</div>
					<div class="text-xs text-text-muted">{trackedRows.filter((r) => r.active).length} active</div>
				</div>
				<div class="engine-row-cards">
					{#each ALL_CAMERA_ROLES.filter((c) => c.role === 'c_channel_2' || c.role === 'c_channel_3' || c.role === AUX_ROLE) as cam (cam.role)}
						{@const tracks = trackedForRole(cam.role)}
						{@const active = tracks.length}
						{@const confirmed = tracks.filter((t) => t.piece.carousel_detected_confirmed_at || t.piece.classification_channel_zone_state === 'tracking').length}
						{@const tone = active > 0 ? 'ok' : 'idle'}
						<div class="engine-card">
							<div class="engine-card-head">
								<span class="engine-dot {toneDotClass(tone)}"></span>
								<div class="engine-card-title">{cam.short} Tracker</div>
								<div class="engine-card-subtitle">{cam.name}</div>
							</div>
							<div class="engine-card-body">
								<div class="engine-stat">
									<div class="engine-stat-label">Active tracks</div>
									<div class="engine-stat-value font-mono">{active}</div>
								</div>
								<div class="engine-stat">
									<div class="engine-stat-label">Confirmed</div>
									<div class="engine-stat-value font-mono">{confirmed}</div>
								</div>
								<div class="engine-stat">
									<div class="engine-stat-label">Stage</div>
									<div class="engine-stat-value font-mono">
										{#if cam.role === AUX_ROLE}
											on-carousel
										{:else}
											pre-handoff
										{/if}
									</div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			</section>

			<div class="engine-arrow" class:engine-arrow-active={rowTone('trackers') === 'ok' && rowTone('pipeline') === 'ok'}></div>

			<!-- ROW: PIPELINE STATE MACHINES -->
			<section class="engine-row">
				<div class="engine-row-label">
					<div class="engine-row-title">Pipeline</div>
					<div class="text-xs text-text-muted">state machines</div>
				</div>
				<div class="engine-row-cards">
					{#each pipelineRows as { name, sm, key } (key)}
						{@const tone = stateMachineTone(sm)}
						{@const age = sm?.entered_at ? formatDuration(nowTs - sm.entered_at) : '—'}
						{@const counts = runtimeCounts}
						<div class="engine-card">
							<div class="engine-card-head">
								<span class="engine-dot {toneDotClass(tone)}"></span>
								<div class="engine-card-title">{name}</div>
								<div class="engine-card-subtitle">{key}</div>
							</div>
							<div class="engine-card-body">
								<div class="engine-stat">
									<div class="engine-stat-label">State</div>
									<div class="engine-stat-value font-mono">{sm?.current_state ?? '—'}</div>
								</div>
								<div class="engine-stat">
									<div class="engine-stat-label">In state</div>
									<div class="engine-stat-value font-mono">{age}</div>
								</div>
								{#if counts && key === 'feeder'}
									<div class="engine-stat">
										<div class="engine-stat-label">Seen</div>
										<div class="engine-stat-value font-mono">{counts.pieces_seen ?? 0}</div>
									</div>
								{:else if counts && key === 'classification'}
									<div class="engine-stat">
										<div class="engine-stat-label">Classified</div>
										<div class="engine-stat-value font-mono">{counts.classified ?? 0}</div>
									</div>
								{:else if counts && key === 'distribution'}
									<div class="engine-stat">
										<div class="engine-stat-label">Distributed</div>
										<div class="engine-stat-value font-mono">{counts.distributed ?? 0}</div>
									</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</section>

			<div class="engine-arrow" class:engine-arrow-active={rowTone('pipeline') === 'ok' && rowTone('hardware') === 'ok'}></div>

			<!-- ROW: HARDWARE -->
			<section class="engine-row">
				<div class="engine-row-label">
					<div class="engine-row-title">Hardware</div>
					<div class="text-xs text-text-muted">{hardwareState}</div>
				</div>
				<div class="engine-row-cards">
					<!-- Steppers / bus summary -->
					<div class="engine-card">
						<div class="engine-card-head">
							<span class="engine-dot {toneDotClass(hardwareTone(hardwareState))}"></span>
							<div class="engine-card-title">Control Bus</div>
							<div class="engine-card-subtitle">steppers</div>
						</div>
						<div class="engine-card-body">
							<div class="engine-stat">
								<div class="engine-stat-label">State</div>
								<div class="engine-stat-value font-mono">{hardwareState}</div>
							</div>
							<div class="engine-stat">
								<div class="engine-stat-label">Error</div>
								<div class="engine-stat-value font-mono truncate" title={hardwareError ?? ''}>
									{hardwareError ?? 'none'}
								</div>
							</div>
							<div class="engine-stat">
								<div class="engine-stat-label">Lifecycle</div>
								<div class="engine-stat-value font-mono">{lifecycleState ?? '—'}</div>
							</div>
						</div>
					</div>

					<!-- Servo bus -->
					<div class="engine-card">
						<div class="engine-card-head">
							<span class="engine-dot {toneDotClass(servoBusOnline ? 'ok' : 'err')}"></span>
							<div class="engine-card-title">Servo Bus</div>
							<div class="engine-card-subtitle">{servoLayers.length} layer{servoLayers.length === 1 ? '' : 's'}</div>
						</div>
						<div class="engine-card-body">
							<div class="engine-stat">
								<div class="engine-stat-label">Bus</div>
								<div class="engine-stat-value font-mono">{servoBusOnline ? 'online' : 'offline'}</div>
							</div>
							<div class="engine-stat">
								<div class="engine-stat-label">Available</div>
								<div class="engine-stat-value font-mono">
									{servoLayersAvailable}/{servoLayers.length}
								</div>
							</div>
							<div class="engine-stat">
								<div class="engine-stat-label">Layers</div>
								<div class="mt-1 flex flex-wrap gap-1">
									{#each servoLayers as layer (layer.layer_index)}
										<span
											class="inline-flex h-5 min-w-[1.25rem] items-center justify-center px-1 text-xs font-mono border {layer.available ? 'border-success/50 bg-success/10 text-success' : 'border-danger/50 bg-danger/10 text-danger'}"
											title={layer.name ?? `layer_${layer.layer_index}`}
										>
											{layer.layer_index}
										</span>
									{/each}
								</div>
							</div>
						</div>
					</div>

					<!-- Bins layout -->
					<div class="engine-card">
						<div class="engine-card-head">
							<span class="engine-dot {toneDotClass(binLayersEnabled > 0 ? 'ok' : 'idle')}"></span>
							<div class="engine-card-title">Storage Bins</div>
							<div class="engine-card-subtitle">distribution</div>
						</div>
						<div class="engine-card-body">
							<div class="engine-stat">
								<div class="engine-stat-label">Layers</div>
								<div class="engine-stat-value font-mono">{binLayersEnabled}/{binLayers.length}</div>
							</div>
							<div class="engine-stat">
								<div class="engine-stat-label">Bins</div>
								<div class="engine-stat-value font-mono">{binTotalBins}</div>
							</div>
							<div class="engine-stat">
								<div class="engine-stat-label">Sections</div>
								<div class="engine-stat-value font-mono">{binTotalSections}</div>
							</div>
						</div>
					</div>
				</div>
			</section>

		</div>
	</div>
</div>

<style>
	.engine-row {
		display: flex;
		gap: 1rem;
		align-items: stretch;
		padding: 0.25rem 0;
	}

	.engine-row-label {
		flex-shrink: 0;
		width: 9rem;
		padding-top: 0.5rem;
	}

	.engine-row-title {
		font-family: var(--font-mono);
		font-size: 0.875rem;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--color-text);
	}

	.engine-row-cards {
		flex: 1;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: 0.75rem;
	}

	.engine-card {
		border: 1px solid var(--color-border);
		background: var(--color-surface);
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.engine-card-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.625rem;
		border-bottom: 1px solid var(--color-border);
		background: color-mix(in oklab, var(--color-surface) 90%, var(--color-bg) 10%);
	}

	.engine-card-title {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--color-text);
		min-width: 0;
		flex-shrink: 0;
	}

	.engine-card-subtitle {
		font-size: 0.75rem;
		font-family: var(--font-mono);
		color: var(--color-text-muted);
		margin-left: auto;
		min-width: 0;
		max-width: 60%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.engine-dot {
		display: inline-block;
		width: 0.5rem;
		height: 0.5rem;
		flex-shrink: 0;
	}

	.engine-card-body {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
		padding: 0.625rem;
	}

	.engine-stat {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 0.5rem;
		min-width: 0;
	}

	.engine-stat-label {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
		flex-shrink: 0;
	}

	.engine-stat-value {
		font-size: 0.875rem;
		color: var(--color-text);
		min-width: 0;
		max-width: 70%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: right;
	}

	.engine-arrow {
		align-self: stretch;
		margin-left: 9rem;
		height: 1.25rem;
		position: relative;
	}

	.engine-arrow::before {
		content: '';
		position: absolute;
		left: 1.25rem;
		top: 0;
		bottom: 0;
		width: 1px;
		background: var(--color-border);
	}

	.engine-arrow::after {
		content: '';
		position: absolute;
		left: 1.25rem;
		bottom: 0;
		transform: translate(-50%, 0);
		width: 0;
		height: 0;
		border-left: 5px solid transparent;
		border-right: 5px solid transparent;
		border-top: 6px solid var(--color-border);
	}

	.engine-arrow-active::before {
		background: var(--color-success);
		animation: engine-pulse 1.8s ease-in-out infinite;
	}

	.engine-arrow-active::after {
		border-top-color: var(--color-success);
	}

	@keyframes engine-pulse {
		0%, 100% { opacity: 0.45; }
		50% { opacity: 1; }
	}
</style>
