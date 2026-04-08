<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount, untrack } from 'svelte';

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

	function formatTelemetryValue(value: number | null): string {
		return value === null ? '--' : String(value);
	}

	function layerIsOffline(layer: LayerDraft): boolean {
		return backend === 'waveshare' && !layer.telemetry.available && !!layer.telemetry.error;
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
			void loadLiveFeedback();
			void loadAvailablePorts();
			if (backend === 'waveshare') {
				void scanBusServosQuiet();
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load storage layer settings';
		} finally {
			loading = false;
		}
	}

	async function scanBusServosQuiet() {
		if (busScanning) return;
		busScanning = true;
		try {
			const scanPort = port.trim() || undefined;
			const url = new URL(`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos`);
			if (scanPort) url.searchParams.set('port', scanPort);
			const res = await fetch(url.toString());
			if (!res.ok) return;
			const payload = await res.json();
			const prevCount = busServos.length;
			busServos = Array.isArray(payload?.servos) ? payload.servos : [];
			busSuggestedNextId = typeof payload?.suggested_next_id === 'number' ? payload.suggested_next_id : null;

			// On first successful scan, auto-assign discovered IDs to layers
			if (prevCount === 0 && busServos.length > 0) {
				autoAssignBusIds();
			}
		} catch {
			// quiet — don't show errors for background scans
		} finally {
			busScanning = false;
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
			const storageLayers = layerBinCounts.map((binCount, index) => ({
				bin_count: binCount,
				enabled: layers[index]?.enabled ?? true
			}));
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
		busScanning = true;
		busError = null;
		busStatusMsg = '';
		try {
			const scanPort = port.trim() || undefined;
			const url = new URL(`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos`);
			if (scanPort) url.searchParams.set('port', scanPort);
			const res = await fetch(url.toString());
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			busServos = Array.isArray(payload?.servos) ? payload.servos : [];
			busSuggestedNextId = typeof payload?.suggested_next_id === 'number' ? payload.suggested_next_id : null;

			// Pre-fill new ID inputs: for ID 1 servos, suggest the next available ID
			const inputs: Record<number, string> = {};
			for (const servo of busServos) {
				if (servo.id === 1 && busSuggestedNextId !== null) {
					inputs[servo.id] = String(busSuggestedNextId);
				}
			}
			newIdInputs = inputs;
		} catch (e: any) {
			busError = e.message ?? 'Failed to scan bus';
		} finally {
			busScanning = false;
		}
	}

	async function loadAvailablePorts() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/waveshare/ports`);
			if (!res.ok) return;
			const payload = await res.json();
			availablePorts = Array.isArray(payload?.ports) ? payload.ports : [];
			portsLoaded = true;
		} catch {
			// silent — keep text input as fallback
		}
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
			// Refresh the servo list
			await scanBusServos();
		} catch (e: any) {
			busError = e.message ?? `Failed to change servo ID from ${oldId} to ${newId}`;
		} finally {
			changingIdFor = null;
		}
	}

	function modelLabel(servo: BusServo): string {
		if (servo.model_name) return servo.model_name;
		if (servo.model !== null) return `SC?? (${servo.model})`;
		return '--';
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
				void loadAvailablePorts();
				void scanBusServosQuiet();
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
				void scanBusServosQuiet();
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
	<div class="flex flex-wrap items-end gap-3">
		<label class="text-xs text-text">
			Backend
			<select
				bind:value={backend}
				disabled={loading || saving}
				class="mt-1 block w-40 border border-border bg-bg px-2 py-1.5 text-sm text-text"
			>
				<option value="pca9685">PCA9685</option>
				<option value="waveshare">Waveshare SC</option>
			</select>
		</label>

		{#if backend === 'pca9685'}
			<label class="text-xs text-text">
				Open Angle
				<input
					type="number"
					min="0"
					max="180"
					step="1"
					bind:value={openAngle}
					disabled={loading || saving}
					class="mt-1 block w-24 border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
			<label class="text-xs text-text">
				Closed Angle
				<input
					type="number"
					min="0"
					max="180"
					step="1"
					bind:value={closedAngle}
					disabled={loading || saving}
					class="mt-1 block w-24 border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		{:else}
			<label class="min-w-0 flex-1 text-xs text-text">
				Port
				{#if portsLoaded && availablePorts.length > 0}
					<select
						bind:value={port}
						disabled={loading || saving}
						class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					>
						<option value="">Auto-detect</option>
						{#each availablePorts as p}
							<option value={p.device}>{p.device} — {p.product}{p.confirmed ? ` (${p.servo_count} servos)` : ''}</option>
						{/each}
					</select>
				{:else}
					<input
						type="text"
						bind:value={port}
						placeholder="Auto-detect"
						disabled={loading || saving}
						class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
				{/if}
			</label>
		{/if}

		<div class="flex items-center gap-2 pb-0.5">
			<button
				onclick={saveSettings}
				disabled={loading || saving || layers.length === 0}
				class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				{saving ? 'Saving...' : 'Save'}
			</button>
			<button
				onclick={loadSettings}
				disabled={loading || saving}
				class="cursor-pointer text-xs text-text-muted hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
			>
				{loading ? 'Loading...' : 'Reload'}
			</button>
		</div>
	</div>

	{#if errorMsg}
		<div class="text-sm text-[#D01012] dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}

	{#if servoIssues.length > 0}
		<div class="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-200">
			<div class="font-medium">Some storage-layer hardware is offline.</div>
			<div class="mt-1 space-y-1 text-xs">
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

	{#if layers.length === 0 && !loading}
		<div class="text-sm text-text-muted">
			No storage layers found.
		</div>
	{:else}
		<div class="overflow-hidden border border-border">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border bg-surface text-left text-xs">
						<th class="px-3 py-2 font-medium text-text-muted">Layer</th>
						<th class="px-3 py-2 font-medium text-text-muted">Active</th>
						<th class="px-3 py-2 font-medium text-text-muted">Bins</th>
						<th class="px-3 py-2 font-medium text-text-muted">{backend === 'waveshare' ? 'Servo ID' : 'Channel'}</th>
						<th class="px-3 py-2 font-medium text-text-muted">Invert</th>
						{#if backend === 'waveshare'}
							<th class="px-3 py-2 font-medium text-text-muted">Position</th>
						{/if}
						<th class="px-3 py-2 font-medium text-text-muted">State</th>
						<th class="px-3 py-2 text-right font-medium text-text-muted">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each layers as layer, index}
						<tr class="border-b border-border bg-bg last:border-b-0 {layer.enabled ? '' : 'opacity-60'}">
							<td class="px-3 py-2 font-medium text-text">{layer.index}</td>
							<td class="px-3 py-2">
								<input
									type="checkbox"
									checked={layer.enabled}
									onchange={(event) => updateLayerEnabled(index, event.currentTarget.checked)}
									disabled={loading || saving}
									aria-label={`Layer ${layer.index} active`}
								/>
							</td>
							<td class="px-3 py-2">
								<select
									value={layer.binCount}
									onchange={(event) => updateLayerCount(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
								>
									{#each allowedCounts as count}
										<option value={String(count)}>{count}</option>
									{/each}
								</select>
							</td>
							<td class="px-3 py-2">
								{#if backend === 'waveshare'}
									<select
										value={layer.servoId}
										onchange={(event) => updateLayerServoId(index, event.currentTarget.value)}
										disabled={loading || saving}
										class="w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
									>
										<option value="">-</option>
										{#each waveshareServoChoices() as servoId}
											<option value={String(servoId)}>{servoId}</option>
										{/each}
									</select>
								{:else}
									<select
										value={layer.servoId}
										onchange={(event) => updateLayerServoId(index, event.currentTarget.value)}
										disabled={loading || saving}
										class="w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
									>
										<option value="">-</option>
										{#each pcaChannelChoices() as channel}
											<option value={String(channel)}>{channel}</option>
										{/each}
									</select>
								{/if}
							</td>
							<td class="px-3 py-2">
								<input
									type="checkbox"
									checked={layer.invert}
									onchange={(event) => void updateLayerInvert(index, event.currentTarget.checked)}
									disabled={loading || saving || !layer.enabled || !layerHasAssignedServo(layer)}
								/>
							</td>
							{#if backend === 'waveshare'}
								<td class="px-3 py-2 font-mono text-xs text-text-muted">
									{#if layerIsOffline(layer)}
										<span class="text-[#D01012] dark:text-red-400">Offline</span>
									{:else}
										{formatTelemetryValue(layer.telemetry.position)}
										<span class="text-text-muted/50">/ {formatTelemetryValue(layer.telemetry.openPosition)} · {formatTelemetryValue(layer.telemetry.closedPosition)}</span>
										{#if layer.telemetry.error}
											<span class="ml-1 text-[#D01012]" title={layer.telemetry.error}>!</span>
										{/if}
									{/if}
								</td>
							{/if}
							<td class="px-3 py-2">
								{#if !layer.enabled}
									<span
										class="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400"
										title="Inactive layers are ignored when assigning bins."
									>
										<span class="h-1.5 w-1.5 rounded-full bg-amber-500"></span>
										Inactive
									</span>
								{:else if layerIsOffline(layer)}
									<span
										class="inline-flex items-center gap-1 text-xs text-[#D01012] dark:text-red-400"
										title={layer.telemetry.error ?? 'Servo offline'}
									>
										<span class="h-1.5 w-1.5 rounded-full bg-[#D01012]"></span>
										Offline
									</span>
								{:else if !layerHasAssignedServo(layer)}
									<span
										class="inline-flex items-center gap-1 text-xs text-text-muted"
										title="No servo assigned to this layer."
									>
										<span class="h-1.5 w-1.5 rounded-full bg-border"></span>
										No servo
									</span>
								{:else if layer.liveOpen !== null}
									<span class="inline-flex items-center gap-1 text-xs {layer.liveOpen ? 'text-[#00852B] dark:text-green-400' : 'text-text-muted'}">
										<span class="h-1.5 w-1.5 rounded-full {layer.liveOpen ? 'bg-[#00852B]' : 'bg-border'}"></span>
										{layer.liveOpen ? 'Open' : 'Closed'}
									</span>
								{:else}
									<span class="text-xs text-text-muted">--</span>
								{/if}
							</td>
							<td class="px-3 py-2 text-right">
								<div class="flex items-center justify-end gap-1.5">
									<button
										onclick={() => toggleLayerServo(index)}
										disabled={loading || saving || layer.testing || !layer.enabled || !layerHasAssignedServo(layer) || layerIsOffline(layer)}
										class="cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
									>
										{#if layer.testing}
											...
										{:else if layer.liveOpen === true}
											Close
										{:else if layer.liveOpen === false}
											Open
										{:else}
											Toggle
										{/if}
									</button>
									{#if backend === 'waveshare'}
										<button
											onclick={() => calibrateLayerServo(index)}
											disabled={loading || saving || layer.calibrating || !layer.enabled || !layerHasAssignedServo(layer) || layerIsOffline(layer)}
											class="cursor-pointer border border-border bg-bg px-2 py-1 text-xs text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
										>
											{layer.calibrating ? '...' : 'Cal'}
										</button>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if backend === 'waveshare'}
		<div class="mt-6 flex flex-col gap-3">
			<div class="flex items-center gap-3">
				<h3 class="text-sm font-medium text-text">Waveshare Servos on Bus</h3>
				<button
					onclick={scanBusServos}
					disabled={busScanning}
					class="cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
				>
					{busScanning ? 'Scanning...' : 'Scan Bus'}
				</button>
			</div>

			{#if busError}
				<div class="text-sm text-[#D01012] dark:text-red-400">{busError}</div>
			{:else if busStatusMsg}
				<div class="text-sm text-text-muted">{busStatusMsg}</div>
			{/if}

			{#if busServos.length > 0}
				<div class="overflow-hidden border border-border">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-border bg-surface text-left text-xs">
								<th class="px-3 py-2 font-medium text-text-muted">ID</th>
								<th class="px-3 py-2 font-medium text-text-muted">Model</th>
								<th class="px-3 py-2 font-medium text-text-muted">Position</th>
								<th class="px-3 py-2 font-medium text-text-muted">Limits</th>
								<th class="px-3 py-2 font-medium text-text-muted">Temp</th>
								<th class="px-3 py-2 font-medium text-text-muted">Voltage</th>
								<th class="px-3 py-2 font-medium text-text-muted">Load</th>
								<th class="px-3 py-2 font-medium text-text-muted">PID</th>
								<th class="px-3 py-2 text-right font-medium text-text-muted">Change ID</th>
							</tr>
						</thead>
						<tbody>
							{#each busServos as servo}
								<tr class="border-b border-border bg-bg last:border-b-0 {servo.id === 1 ? 'bg-amber-50 dark:bg-amber-950/20' : ''}">
									<td class="px-3 py-2 font-medium text-text">
										{servo.id}
										{#if servo.id === 1}
											<span class="ml-1 text-xs text-amber-600 dark:text-amber-400" title="Factory default ID — assign a unique ID before use">Factory</span>
										{/if}
									</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">{modelLabel(servo)}</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">{servo.position ?? '--'}</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">
										{servo.min_limit ?? '--'} – {servo.max_limit ?? '--'}
									</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">
										{servo.temperature !== null && servo.temperature !== undefined ? `${servo.temperature}°C` : '--'}
									</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">
										{servo.voltage !== null && servo.voltage !== undefined ? `${servo.voltage}V` : '--'}
									</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">
										{servo.load ?? '--'}
									</td>
									<td class="px-3 py-2 font-mono text-xs text-text-muted">
										{#if servo.pid}
											{servo.pid.p}/{servo.pid.d}/{servo.pid.i}
										{:else}
											--
										{/if}
									</td>
									<td class="px-3 py-2 text-right">
										<div class="flex items-center justify-end gap-1.5">
											<input
												type="number"
												min="1"
												max="253"
												value={newIdInputs[servo.id] ?? ''}
												oninput={(e) => {
													newIdInputs = { ...newIdInputs, [servo.id]: e.currentTarget.value };
												}}
												placeholder={servo.id === 1 && busSuggestedNextId ? String(busSuggestedNextId) : 'New ID'}
												disabled={changingIdFor !== null}
												class="w-20 border border-border bg-surface px-1.5 py-1 text-xs text-text"
											/>
											<button
												onclick={() => changeServoId(servo.id)}
												disabled={changingIdFor !== null || !newIdInputs[servo.id]}
												class="cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
											>
												{changingIdFor === servo.id ? '...' : 'Set'}
											</button>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if !busScanning}
				<div class="text-xs text-text-muted">
					{#if !port && availablePorts.length === 0}
						Select a port above and save before scanning, or connect the Waveshare servo board.
					{:else}
						Press "Scan Bus" to detect connected servos.
					{/if}
				</div>
			{/if}
		</div>
	{/if}
	{/if}
</div>
