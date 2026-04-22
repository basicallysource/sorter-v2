<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount, untrack } from 'svelte';
	import { CheckCircle2, RefreshCcw } from 'lucide-svelte';
	import BackendToolbar from './storage/BackendToolbar.svelte';
	import LayerList from './storage/LayerList.svelte';
	import WaveshareBusTable from './storage/WaveshareBusTable.svelte';

	type ServoBackend = 'pca9685' | 'waveshare';
	type LayerTelemetry = {
		available: boolean;
		position: number | null;
		angle: number | null;
		openPosition: number | null;
		closedPosition: number | null;
		minLimit: number | null;
		maxLimit: number | null;
		isOpen: boolean | null;
		error: string | null;
	};
	type HardwareIssue = {
		kind: string;
		backend?: string;
		layer_index?: number;
		servo_id?: number;
		message: string;
	};
	type LayerDraft = {
		index: number;
		binCount: string;
		enabled: boolean;
		servoId: string;
		invert: boolean;
		maxPiecesPerBin: string;
		liveOpen: boolean | null;
		telemetry: LayerTelemetry;
		testing: boolean;
		calibrating: boolean;
	};

	type BusServo = {
		id: number;
		model: number | null;
		model_name: string | null;
		position: number | null;
		load: number | null;
		min_limit: number | null;
		max_limit: number | null;
		voltage: number | null;
		temperature: number | null;
		current: number | null;
		pid: { p: number; d: number; i: number } | null;
		error?: string;
	};

	type WaveshareInventoryPayload = {
		current_port?: string | null;
		ports?: WavesharePort[];
		servos?: BusServo[];
		highest_seen_id?: number;
		suggested_next_id?: number | null;
		scanning?: boolean;
		last_error?: string | null;
	};

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loaded = $state(false);
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let allowedCounts = $state<number[]>([12, 18, 30]);
	let availableServoIds = $state<number[]>([]);
	let servoIssues = $state<HardwareIssue[]>([]);
	let backend = $state<ServoBackend>('pca9685');
	let openAngle = $state(10);
	let closedAngle = $state(83);
	let port = $state('');
	let layers = $state<LayerDraft[]>([]);
	let liveFeedbackRequestInFlight = false;
	let baselineSnapshot = $state('');

	const currentSnapshot = $derived(
		JSON.stringify({
			backend,
			openAngle,
			closedAngle,
			port: port.trim(),
			layers: layers.map((l) => ({
				binCount: l.binCount,
				enabled: l.enabled,
				servoId: l.servoId.trim(),
				invert: l.invert,
				maxPiecesPerBin: l.maxPiecesPerBin.trim()
			}))
		})
	);
	const isDirty = $derived(loaded && baselineSnapshot !== currentSnapshot);

	// Waveshare servo bus management
	let busServos = $state<BusServo[]>([]);
	let busScanning = $state(false);
	let busSuggestedNextId = $state<number | null>(null);
	let busError = $state<string | null>(null);
	let busStatusMsg = $state('');
	let changingIdFor = $state<number | null>(null);
	let newIdInputs = $state<Record<number, string>>({});

	// Waveshare port discovery
	type WavesharePort = { device: string; product: string; serial: string | null; confirmed?: boolean; servo_count?: number };
	let availablePorts = $state<WavesharePort[]>([]);
	let portsLoaded = $state(false);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function pcaChannelChoices(): number[] {
		return availableServoIds.length > 0
			? availableServoIds
			: Array.from({ length: layers.length }, (_, index) => index);
	}

	function waveshareServoChoices(): number[] {
		const ids = new Set<number>();

		// Primary source: IDs actually found on the bus
		if (busServos.length > 0) {
			for (const servo of busServos) {
				if (servo.id >= 1 && servo.id <= 253) ids.add(servo.id);
			}
		} else if (availableServoIds.length > 0) {
			// Fallback: IDs reported by the backend (includes its own scan)
			for (const id of availableServoIds) ids.add(id);
		}

		// If still empty (no scan yet), offer 1..layerCount as placeholder
		if (ids.size === 0) {
			for (let i = 1; i <= Math.max(layers.length, 1); i++) ids.add(i);
		}

		return [...ids].sort((a, b) => a - b);
	}

	function layerHasAssignedServo(layer: LayerDraft): boolean {
		return layer.servoId.trim().length > 0;
	}

	function emptyTelemetry(): LayerTelemetry {
		return {
			available: false,
			position: null,
			angle: null,
			openPosition: null,
			closedPosition: null,
			minLimit: null,
			maxLimit: null,
			isOpen: null,
			error: null
		};
	}

	function toNumberOrNull(value: unknown): number | null {
		return typeof value === 'number' && Number.isFinite(value) ? value : null;
	}

	function normalizeTelemetry(payload: any): LayerTelemetry {
		if (!payload || typeof payload !== 'object') {
			return emptyTelemetry();
		}

		return {
			available: Boolean(payload.available),
			position: toNumberOrNull(payload.position),
			angle: toNumberOrNull(payload.angle),
			openPosition: toNumberOrNull(payload.open_position),
			closedPosition: toNumberOrNull(payload.closed_position),
			minLimit: toNumberOrNull(payload.min_limit),
			maxLimit: toNumberOrNull(payload.max_limit),
			isOpen: typeof payload.is_open === 'boolean' ? payload.is_open : null,
			error: typeof payload.error === 'string' && payload.error.length > 0 ? payload.error : null
		};
	}

	function applyTelemetryPayload(entries: any[]) {
		const byLayerIndex = new Map<number, LayerTelemetry>();
		for (const entry of entries) {
			const layerIndex = Number(entry?.layer_index);
			if (!Number.isInteger(layerIndex)) continue;
			byLayerIndex.set(layerIndex, normalizeTelemetry(entry));
		}

		layers = layers.map((layer, index) => {
			const telemetry = byLayerIndex.get(index) ?? layer.telemetry;
			return {
				...layer,
				telemetry,
				liveOpen: telemetry.isOpen ?? layer.liveOpen
			};
		});
	}

	function updateLayerTelemetry(index: number, payload: any) {
		const telemetry = normalizeTelemetry(payload);
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index
				? {
						...layer,
						telemetry,
						liveOpen: telemetry.isOpen ?? layer.liveOpen
					}
				: layer
		);
	}

function applySettings(payload: any) {
		const storage = payload?.storage_layers ?? payload?.settings ?? {};
		const servo = payload?.servo ?? {};
		const previousStates = new Map(
			layers.map((layer) => [layer.index, { liveOpen: layer.liveOpen, telemetry: layer.telemetry }])
		);

		allowedCounts = Array.isArray(storage?.allowed_bin_counts)
			? storage.allowed_bin_counts.filter((value: unknown): value is number => typeof value === 'number')
			: [12, 18, 30];

		backend = servo.backend === 'waveshare' ? 'waveshare' : 'pca9685';
		openAngle = Number(servo.open_angle ?? 10);
		closedAngle = Number(servo.closed_angle ?? 83);
		port = typeof servo.port === 'string' ? servo.port : '';
		availableServoIds = Array.isArray(servo.available_channel_ids)
			? servo.available_channel_ids.filter((value: unknown): value is number => typeof value === 'number')
			: [];
		servoIssues = Array.isArray(servo.issues)
			? servo.issues.filter(
					(value: unknown): value is HardwareIssue =>
						typeof value === 'object' &&
						value !== null &&
						typeof (value as HardwareIssue).kind === 'string' &&
						typeof (value as HardwareIssue).message === 'string'
				)
			: [];

		const storageLayers = Array.isArray(storage?.layers) ? storage.layers : [];
		const servoChannels = Array.isArray(servo?.channels) ? servo.channels : [];
		layers = storageLayers.map((layer: any, index: number) => ({
			index: Number(layer?.index ?? index + 1),
			binCount: String(Number(layer?.bin_count ?? 12)),
			enabled: layer?.enabled !== false,
			servoId:
				servoChannels[index]?.id === null || servoChannels[index]?.id === undefined
					? ''
					: String(Number(servoChannels[index].id)),
			invert: Boolean(servoChannels[index]?.invert),
			maxPiecesPerBin:
				typeof layer?.max_pieces_per_bin === 'number' && layer.max_pieces_per_bin > 0
					? String(Math.floor(layer.max_pieces_per_bin))
					: '',
			liveOpen: previousStates.get(Number(layer?.index ?? index + 1))?.liveOpen ?? null,
			telemetry: previousStates.get(Number(layer?.index ?? index + 1))?.telemetry ?? emptyTelemetry(),
			testing: false,
			calibrating: false
		}));
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			applySettings(await res.json());
			loaded = true;
			baselineSnapshot = currentSnapshot;
			void loadLiveFeedback();
			if (backend === 'waveshare') {
				void loadWaveshareInventory({ refresh: false, silent: true });
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load storage layer settings';
		} finally {
			loading = false;
		}
	}

	function applyWaveshareInventory(
		payload: WaveshareInventoryPayload,
		options: { seedNewIds?: boolean } = {}
	) {
		availablePorts = Array.isArray(payload?.ports) ? payload.ports : [];
		portsLoaded = true;
		const previousCount = busServos.length;
		busServos = Array.isArray(payload?.servos) ? payload.servos : [];
		busSuggestedNextId =
			typeof payload?.suggested_next_id === 'number' ? payload.suggested_next_id : null;
		if (!port.trim() && typeof payload?.current_port === 'string' && payload.current_port) {
			port = payload.current_port;
		}

		if (options.seedNewIds) {
			const inputs: Record<number, string> = {};
			for (const servo of busServos) {
				if (servo.id === 1 && busSuggestedNextId !== null) {
					inputs[servo.id] = String(busSuggestedNextId);
				}
			}
			newIdInputs = inputs;
		}

		if (previousCount === 0 && busServos.length > 0) {
			autoAssignBusIds();
		}
	}

	async function loadWaveshareInventory(
		options: { refresh?: boolean; silent?: boolean; seedNewIds?: boolean } = {}
	) {
		const refresh = options.refresh === true;
		if (refresh && busScanning) return;
		if (refresh) {
			busScanning = true;
		}
		if (!options.silent) {
			busError = null;
			busStatusMsg = '';
		}
		try {
			const scanPort = port.trim() || undefined;
			const url = new URL(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/${refresh ? 'rescan' : 'status'}`
			);
			if (scanPort) url.searchParams.set('port', scanPort);
			const res = await fetch(url.toString(), { method: refresh ? 'POST' : 'GET' });
			if (!res.ok) throw new Error(await res.text());
			applyWaveshareInventory(await res.json(), { seedNewIds: options.seedNewIds });
		} catch (e: any) {
			if (!options.silent) {
				busError = e.message ?? 'Failed to load Waveshare bus inventory';
			}
		} finally {
			if (refresh) {
				busScanning = false;
			}
		}
	}

	function autoAssignBusIds() {
		const scannedIds = busServos.map((s) => s.id).sort((a, b) => a - b);
		if (scannedIds.length === 0) return;

		// Check if any enabled layer already has a valid scanned ID
		const alreadyAssigned = layers.some(
			(l) => l.enabled && layerHasAssignedServo(l) && scannedIds.includes(Number(l.servoId))
		);
		if (alreadyAssigned) return;

		let nextIndex = 0;
		layers = layers.map((layer) => {
			if (!layer.enabled || layerHasAssignedServo(layer)) return layer;
			const assignedId = scannedIds[nextIndex] ?? scannedIds[scannedIds.length - 1];
			nextIndex += 1;
			return { ...layer, servoId: String(assignedId) };
		});
	}

	async function loadLiveFeedback() {
		if (backend !== 'waveshare' || liveFeedbackRequestInFlight) {
			return;
		}

		liveFeedbackRequestInFlight = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/servo/live`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			if (payload?.backend !== 'waveshare') {
				return;
			}
			const entries = Array.isArray(payload?.layers) ? payload.layers : [];
			applyTelemetryPayload(entries);
		} catch {
			// Keep the last known telemetry; polling should be quiet on transient bus hiccups.
		} finally {
			liveFeedbackRequestInFlight = false;
		}
	}

	function parsedLayerCounts(): number[] {
		return layers.map((layer) => {
			const count = Number(layer.binCount);
			if (!allowedCounts.includes(count)) {
				throw new Error(`Layer ${layer.index} must use one of ${allowedCounts.join(', ')} bins.`);
			}
			return count;
		});
	}

	function parsedServoChannels(): Array<{ id: number | null; invert: boolean }> {
		const seenIds = new Set<number>();
		const validPcaChannels = new Set(pcaChannelChoices());

		return layers.map((layer) => {
			if (!layerHasAssignedServo(layer)) {
				if (layer.enabled) {
					throw new Error(`Layer ${layer.index} needs a servo assignment while it is active.`);
				}
				return { id: null, invert: layer.invert };
			}

			const id = Number(layer.servoId);
			if (!Number.isInteger(id)) {
				throw new Error(`Layer ${layer.index} needs a valid servo assignment.`);
			}
			if (backend === 'waveshare') {
				if (id < 1 || id > 253) {
					throw new Error(`Layer ${layer.index} needs a Waveshare servo ID between 1 and 253.`);
				}
			} else if (id < 0 || (validPcaChannels.size > 0 && !validPcaChannels.has(id))) {
				throw new Error(`Layer ${layer.index} needs a valid PCA servo channel.`);
			}
			if (seenIds.has(id)) {
				throw new Error(`Servo assignment ${id} is used more than once.`);
			}
			seenIds.add(id);
			return { id, invert: layer.invert };
		});
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const layerBinCounts = parsedLayerCounts();
			const storageLayers = layerBinCounts.map((binCount, index) => {
				const draft = layers[index];
				const trimmed = draft?.maxPiecesPerBin.trim() ?? '';
				let maxPiecesPerBin: number | null = null;
				if (trimmed.length > 0) {
					const parsed = Number(trimmed);
					if (!Number.isInteger(parsed) || parsed <= 0) {
						throw new Error(`Layer ${draft?.index ?? index + 1} max pieces per bin must be a positive integer.`);
					}
					maxPiecesPerBin = parsed;
				}
				return {
					bin_count: binCount,
					enabled: draft?.enabled ?? true,
					max_pieces_per_bin: maxPiecesPerBin
				};
			});
			const channels = parsedServoChannels();

			const storageRes = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/storage-layers`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layer_bin_counts: layerBinCounts, layers: storageLayers })
			});
			if (!storageRes.ok) throw new Error(await storageRes.text());
			const storagePayload = await storageRes.json();

			const servoRes = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/servo`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					backend,
					open_angle: openAngle,
					closed_angle: closedAngle,
					port: backend === 'waveshare' ? port.trim() || null : null,
					channels
				})
			});
			if (!servoRes.ok) throw new Error(await servoRes.text());
			const servoPayload = await servoRes.json();

			// If a restart is required, clear stale issues — they reflect the old config
			if (servoPayload?.restart_required) {
				servoIssues = [];
			}

			applySettings({
				storage_layers: storagePayload?.settings ?? storagePayload?.storage_layers,
				servo: servoPayload?.settings
			});

			if (servoPayload?.restart_required) {
				servoIssues = [];
			}

			await loadSettings();
			baselineSnapshot = currentSnapshot;

			statusMsg = [storagePayload?.message, servoPayload?.message].filter(Boolean).join(' ');
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save storage layer settings';
		} finally {
			saving = false;
		}
	}

	async function toggleLayerServo(index: number) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, testing: true } : layer
		);
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/servo/layers/${index}/toggle`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			layers = layers.map((layer, layerIndex) =>
				layerIndex === index
					? { ...layer, testing: false, liveOpen: Boolean(payload?.is_open) }
					: layer
			);
			updateLayerTelemetry(index, payload?.feedback);
			statusMsg = payload?.message ?? `Layer ${index + 1} servo toggled.`;
		} catch (e: any) {
			layers = layers.map((layer, layerIndex) =>
				layerIndex === index ? { ...layer, testing: false } : layer
			);
			errorMsg = e.message ?? `Failed to toggle layer ${index + 1} servo`;
		}
	}

	async function calibrateLayerServo(index: number) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, calibrating: true } : layer
		);
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/servo/layers/${index}/calibrate`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			layers = layers.map((layer, layerIndex) =>
				layerIndex === index ? { ...layer, calibrating: false } : layer
			);
			updateLayerTelemetry(index, payload?.feedback);
			statusMsg = payload?.message ?? `Layer ${index + 1} servo calibrated.`;
		} catch (e: any) {
			layers = layers.map((layer, layerIndex) =>
				layerIndex === index ? { ...layer, calibrating: false } : layer
			);
			errorMsg = e.message ?? `Failed to calibrate layer ${index + 1} servo`;
		}
	}

	async function scanBusServos() {
		await loadWaveshareInventory({ refresh: true, silent: false, seedNewIds: true });
	}

	async function loadAvailablePorts() {
		await loadWaveshareInventory({ refresh: false, silent: true });
	}

	async function changeServoId(oldId: number) {
		const rawNewId = newIdInputs[oldId];
		const newId = Number(rawNewId);
		if (!Number.isInteger(newId) || newId < 1 || newId > 253) {
			busError = 'New ID must be between 1 and 253.';
			return;
		}
		if (newId === oldId) {
			busError = 'New ID is the same as the current ID.';
			return;
		}

		changingIdFor = oldId;
		busError = null;
		busStatusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos/${oldId}/set-id`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ new_id: newId })
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			busStatusMsg = payload?.message ?? `ID changed from ${oldId} to ${newId}.`;
			await loadWaveshareInventory({ refresh: true, silent: false, seedNewIds: true });
		} catch (e: any) {
			busError = e.message ?? `Failed to change servo ID from ${oldId} to ${newId}`;
		} finally {
			changingIdFor = null;
		}
	}

function addLayer() {
		const nextIndex = layers.length > 0 ? Math.max(...layers.map((l) => l.index)) + 1 : 1;
		layers = [
			...layers,
			{
				index: nextIndex,
				binCount: '12',
				enabled: true,
				servoId: '',
				invert: false,
				maxPiecesPerBin: '',
				liveOpen: null,
				telemetry: emptyTelemetry(),
				testing: false,
				calibrating: false
			}
		];
	}

	function updateLayerMaxPieces(index: number, value: string) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, maxPiecesPerBin: value } : layer
		);
	}

	function removeLayer(index: number) {
		const layer = layers[index];
		const label = layer ? `Layer ${layer.index}` : `layer ${index + 1}`;
		if (!window.confirm(`Remove ${label}? This only changes the draft — Save to apply.`)) return;
		layers = layers
			.filter((_, i) => i !== index)
			.map((layer, i) => ({ ...layer, index: i + 1 }));
	}

	function updateLayerCount(index: number, value: string) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, binCount: value } : layer
		);
	}

	function updateLayerEnabled(index: number, value: boolean) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index
				? {
					...layer,
					enabled: value
				}
				: layer
		);
	}

	function updateLayerServoId(index: number, value: string) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index
				? {
					...layer,
					servoId: value,
					enabled: value.trim().length > 0 ? layer.enabled : false
				}
				: layer
		);
	}

	async function updateLayerInvert(index: number, value: boolean) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, invert: value } : layer
		);

		const layer = layers[index];
		if (!layer || layer.liveOpen === null) {
			return;
		}

		layers = layers.map((entry, layerIndex) =>
			layerIndex === index ? { ...entry, testing: true } : entry
		);
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/servo/layers/${index}/preview`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						invert: value,
						is_open: layer.liveOpen
					})
				}
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			layers = layers.map((entry, layerIndex) =>
				layerIndex === index
					? {
							...entry,
							testing: false,
							liveOpen: Boolean(payload?.is_open),
							invert: Boolean(payload?.invert)
						}
					: entry
			);
			updateLayerTelemetry(index, payload?.feedback);
			statusMsg = payload?.message ?? `Layer ${index + 1} invert preview updated.`;
		} catch (e: any) {
			layers = layers.map((entry, layerIndex) =>
				layerIndex === index ? { ...entry, testing: false } : entry
			);
			errorMsg = e.message ?? `Failed to preview invert for layer ${index + 1}`;
		}
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});

	let previousBackend: ServoBackend | null = null;

	$effect(() => {
		const current = backend;
		const prev = untrack(() => previousBackend);
		if (prev !== null && prev !== current && layers.length > 0) {
			// Remap servo IDs when switching backends
			if (current === 'waveshare') {
				// PCA→Waveshare: ensure 1-indexed unique IDs
				layers = layers.map((layer, index) => ({
					...layer,
					servoId: layer.enabled ? String(index + 1) : ''
				}));
				void loadWaveshareInventory({ refresh: false, silent: true });
			} else {
				// Waveshare→PCA: switch to 0-indexed channels
				layers = layers.map((layer, index) => ({
					...layer,
					servoId: layer.enabled ? String(index) : ''
				}));
			}
		}
		previousBackend = current;
	});

	$effect(() => {
		loadedMachineKey;
		backend;
		void loadLiveFeedback();
	});

	onMount(() => {
		const feedbackInterval = setInterval(() => {
			void loadLiveFeedback();
		}, 500);
		const busScanInterval = setInterval(() => {
			if (backend === 'waveshare') {
				void loadWaveshareInventory({ refresh: false, silent: true });
			}
		}, 10000);
		return () => {
			clearInterval(feedbackInterval);
			clearInterval(busScanInterval);
		};
	});
</script>

<div class="flex flex-col gap-4">
	{#if !loaded}
		<div class="text-sm text-text-muted">{loading ? 'Loading...' : ''}</div>
	{:else}
		<BackendToolbar
			bind:backend
			bind:openAngle
			bind:closedAngle
			bind:port
			{availablePorts}
			{portsLoaded}
			{loading}
			{saving}
		/>

		{#if servoIssues.length > 0}
			<div
				class="border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-200"
			>
				<div class="font-medium">Some storage-layer hardware is offline.</div>
				<div class="mt-1 space-y-1 text-sm">
					{#each servoIssues as issue}
						<div>
							{#if typeof issue.layer_index === 'number'}
								Layer {issue.layer_index + 1}
								{#if typeof issue.servo_id === 'number'}
									servo {issue.servo_id}
								{/if}
								:
							{/if}
							{issue.message}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<LayerList
			{layers}
			{backend}
			{loading}
			{saving}
			{allowedCounts}
			pcaChannelChoices={pcaChannelChoices()}
			waveshareServoChoices={waveshareServoChoices()}
			onAdd={addLayer}
			onRemove={removeLayer}
			onUpdateCount={updateLayerCount}
			onUpdateEnabled={updateLayerEnabled}
			onUpdateServoId={updateLayerServoId}
			onUpdateInvert={(index, value) => void updateLayerInvert(index, value)}
			onUpdateMaxPieces={updateLayerMaxPieces}
			onToggle={toggleLayerServo}
			onCalibrate={calibrateLayerServo}
		/>

		{#if backend === 'waveshare'}
			<WaveshareBusTable
				{busServos}
				{busScanning}
				{busError}
				{busStatusMsg}
				{busSuggestedNextId}
				{changingIdFor}
				bind:newIdInputs
				{port}
				{availablePorts}
				onScan={scanBusServos}
				onChangeId={changeServoId}
			/>
		{/if}

		<div
			class="sticky bottom-0 z-10 flex flex-col gap-2 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur sm:flex-row sm:items-center sm:justify-between"
		>
			<div class="min-w-0 flex-1 text-sm">
				{#if errorMsg}
					<span class="text-danger dark:text-red-400">{errorMsg}</span>
				{:else if statusMsg}
					<span class="text-text-muted">{statusMsg}</span>
				{:else if isDirty}
					<span class="font-medium text-warning">Unsaved changes — click Save to apply.</span>
				{:else}
					<span class="text-text-muted">All changes saved.</span>
				{/if}
			</div>
			<div class="flex items-center gap-2">
				<button
					onclick={loadSettings}
					disabled={loading || saving}
					class="setup-button-secondary inline-flex items-center gap-1.5 px-3 py-2 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50"
					title="Reload from server"
				>
					<RefreshCcw size={14} />
					{loading ? 'Loading…' : 'Reload'}
				</button>
				<button
					onclick={saveSettings}
					disabled={loading || saving || layers.length === 0 || !isDirty}
					class="setup-button-primary inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
				>
					<CheckCircle2 size={14} />
					{saving ? 'Saving…' : 'Save Changes'}
				</button>
			</div>
		</div>
	{/if}
</div>
