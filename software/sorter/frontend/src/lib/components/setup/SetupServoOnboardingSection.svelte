<script lang="ts">
	import { Plus, Trash2 } from 'lucide-svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';
	import SerialPortPanel from './servo/SerialPortPanel.svelte';
	import ServoInventoryList from './servo/ServoInventoryList.svelte';
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';

	type ServoBackend = 'pca9685' | 'waveshare';
	const MIN_WAVESHARE_CALIBRATED_SPAN = 80;

	type HardwareIssue = {
		kind: string;
		backend?: string;
		layer_index?: number;
		servo_id?: number;
		message: string;
	};

	type WavesharePort = {
		device: string;
		product: string;
		serial: string | null;
		confirmed?: boolean;
		servo_count?: number;
	};

	type BusServo = {
		id: number;
		model: number | null;
		model_name: string | null;
		position: number | null;
		min_limit?: number | null;
		max_limit?: number | null;
		voltage?: number | null;
		temperature?: number | null;
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

	type ServoSource = 'waveshare' | 'pca';

	type StorageLayerDraft = {
		bin_count: number;
		enabled: boolean;
		max_pieces_per_bin: number | null;
		max_dimension_mm: number | null;
	};

	let {
		servoSource = 'pca',
		discoveredServoSource = 'pca',
		discoveredWaveshareServos = 0,
		onSaved = null,
		onSourceChange = null
	}: {
		servoSource?: ServoSource;
		discoveredServoSource?: ServoSource;
		discoveredWaveshareServos?: number;
		onSaved?: (() => void | Promise<void>) | null;
		onSourceChange?: ((value: ServoSource) => void) | null;
	} = $props();

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let settingsLoaded = $state(false);
	let saving = $state(false);
	let scanningBus = $state(false);
	let loadingPorts = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');

	let backend = $state<ServoBackend>('pca9685');
	// open/close angles are still persisted (PCA needs them) but not exposed for waveshare.
	let openAngle = $state(10);
	let closedAngle = $state(83);
	let port = $state('');
	let availableServoIds = $state<number[]>([]);
	let availablePorts = $state<WavesharePort[]>([]);
	let busServos = $state<BusServo[]>([]);
	let suggestedNextId = $state<number | null>(null);
	let highestSeenId = $state<number>(0);
	let servoIssues = $state<HardwareIssue[]>([]);

	let layerCount = $state<number>(0);
	let storageLayers = $state<StorageLayerDraft[]>([]);
	let allowedBinCounts = $state<number[]>([6, 12, 18, 30]);
	// servoId → layer index (1-based). For PCA, channelId → layer index.
	let layerByAssignment = $state<Record<number, number>>({});
	// per-layer invert (1-based layer index → invert)
	let invertByLayer = $state<Record<number, boolean>>({});

	// per-layer angle overrides (1-based layer index → angle or empty string for "use global")
	let openAngleByLayer = $state<Record<number, string>>({});
	let closedAngleByLayer = $state<Record<number, string>>({});

	// estimated angle after nudge, per layer (1-based) for PCA where no feedback exists
	let estimatedAngleByLayer = $state<Record<number, number>>({});

	// per-servo UI state
	let busyByServoId = $state<Record<number, string>>({}); // 'calibrating' | 'moving' | 'promoting'
	let lastMoveByServoId = $state<Record<number, 'open' | 'close' | 'center'>>({});
	// Track servo ids we've already auto-promoted this session so we don't loop.
	let autoPromotedIds = $state<Set<number>>(new Set());

	let selectedServoId = $state<number | null>(null);
	let selectedLayerIdx = $state<number | null>(null);
	let nudgeDegrees = $state<number>(5);

	const activeLayerCount = $derived(storageLayers.filter((layer) => layer.enabled).length);
	const assignedLayerCount = $derived(usedLayersForBusServos().size);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function pcaChoices(): number[] {
		return availableServoIds.length > 0
			? availableServoIds
			: Array.from({ length: Math.max(layerCount, 1) }, (_, index) => index);
	}

	function servoSetupState(servo: BusServo) {
		const minLimit = typeof servo.min_limit === 'number' ? servo.min_limit : null;
		const maxLimit = typeof servo.max_limit === 'number' ? servo.max_limit : null;
		const hasStoredLimits = minLimit !== null && maxLimit !== null;
		const span = hasStoredLimits ? maxLimit - minLimit : 0;
		const looksLikeFactoryRange = hasStoredLimits && minLimit <= 5 && maxLimit >= 1017;
		const calibrated =
			hasStoredLimits &&
			span >= MIN_WAVESHARE_CALIBRATED_SPAN &&
			!looksLikeFactoryRange;
		const layer = layerByAssignment[servo.id] ?? 0;
		const inverted = layer > 0 ? Boolean(invertByLayer[layer]) : false;
		const isFactory = servo.id === 1 && suggestedNextId !== null;

		if (isFactory) {
			return {
				calibrated,
				layer,
				inverted,
				isFactory,
				state: 'factory' as const,
				accent: 'border-l-[var(--color-warning)]',
				headerTone: 'bg-[#FFF7E0]',
				title: 'Promote ID before continuing',
				description: `Factory ID 1 detected. Promote it to ID ${suggestedNextId} before connecting the next servo.`
			};
		}

		if (!calibrated) {
			return {
				calibrated,
				layer,
				inverted,
				isFactory,
				state: 'needs-calibration' as const,
				accent: 'border-l-[#C9C7C0]',
				headerTone: 'bg-bg/40',
				title: 'Needs calibration',
				description: 'Run auto-calibration before testing movement or assigning direction.'
			};
		}

		if (layer === 0) {
			return {
				calibrated,
				layer,
				inverted,
				isFactory,
				state: 'needs-assignment' as const,
				accent: 'border-l-primary',
				headerTone: 'bg-primary/[0.06]',
				title: 'Ready for assignment',
				description: 'Calibration is done. Assign this servo to a storage layer next.'
			};
		}

		return {
			calibrated,
			layer,
			inverted,
			isFactory,
			state: 'ready' as const,
			accent: 'border-l-[var(--color-success)]',
			headerTone: 'bg-success/[0.06]',
			title: 'Setup complete',
			description: `Calibrated and assigned to Layer ${layer}. Test the motion if you want a final check.`
		};
	}

	function applySettings(payload: any) {
		const storage = payload?.storage_layers ?? {};
		const servo = payload?.servo ?? {};
		const storageLayersRaw = Array.isArray(storage?.layers) ? storage.layers : [];
		const servoChannels = Array.isArray(servo?.channels) ? servo.channels : [];
		const persistedBackend = servo?.backend === 'waveshare' ? 'waveshare' : 'pca9685';
		allowedBinCounts = Array.isArray(storage?.allowed_bin_counts)
			? storage.allowed_bin_counts.filter((value: unknown): value is number => typeof value === 'number')
			: [6, 12, 18, 30];

		backend = servoSource === 'waveshare' ? 'waveshare' : 'pca9685';
		openAngle = Number(servo.open_angle ?? 10);
		closedAngle = Number(servo.closed_angle ?? 83);
		port = typeof servo.port === 'string' ? servo.port : '';
		availableServoIds = Array.isArray(servo.available_channel_ids)
			? servo.available_channel_ids.filter(
					(value: unknown): value is number => typeof value === 'number'
				)
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

		layerCount =
			storageLayersRaw.length > 0 ? storageLayersRaw.length : Number(servo.layer_count ?? 0);
		storageLayers = Array.from({ length: layerCount }, (_, index) => {
			const sl = storageLayersRaw[index] ?? {};
			return {
				bin_count: Number(sl?.bin_count ?? allowedBinCounts[0] ?? 12),
				enabled: sl?.enabled !== false,
				max_pieces_per_bin:
					typeof sl?.max_pieces_per_bin === 'number' ? sl.max_pieces_per_bin : null,
				max_dimension_mm: typeof sl?.max_dimension_mm === 'number' ? sl.max_dimension_mm : null
			};
		});

		const newAssignments: Record<number, number> = {};
		const newInverts: Record<number, boolean> = {};
		if (persistedBackend === backend) {
			for (let i = 0; i < layerCount; i++) {
				const channel = servoChannels[i];
				if (channel && typeof channel.id === 'number') {
					newAssignments[channel.id] = i + 1;
					newInverts[i + 1] = Boolean(channel.invert);
				} else if (channel) {
					newInverts[i + 1] = Boolean(channel.invert);
				}
			}
		}
		layerByAssignment = newAssignments;
		invertByLayer = newInverts;

		const newOpenAngles: Record<number, string> = {};
		const newClosedAngles: Record<number, string> = {};
		for (let i = 0; i < storageLayersRaw.length; i++) {
			const sl = storageLayersRaw[i];
			if (typeof sl?.servo_open_angle === 'number') {
				newOpenAngles[i + 1] = String(sl.servo_open_angle);
			}
			if (typeof sl?.servo_closed_angle === 'number') {
				newClosedAngles[i + 1] = String(sl.servo_closed_angle);
			}
		}
		openAngleByLayer = newOpenAngles;
		closedAngleByLayer = newClosedAngles;
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			applySettings(await res.json());
			settingsLoaded = true;
			if (backend === 'waveshare') {
				void loadWaveshareInventory({ refresh: false, silent: true });
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load servo setup';
		} finally {
			loading = false;
		}
	}

	async function loadPorts() {
		loadingPorts = true;
		try {
			await loadWaveshareInventory({ refresh: false, silent: true });
		} finally {
			loadingPorts = false;
		}
	}

	function applyWaveshareInventory(payload: WaveshareInventoryPayload) {
		availablePorts = Array.isArray(payload?.ports) ? payload.ports : [];
		const previousCount = busServos.length;
		busServos = Array.isArray(payload?.servos) ? payload.servos : [];
		suggestedNextId =
			typeof payload?.suggested_next_id === 'number' ? payload.suggested_next_id : null;
		highestSeenId = typeof payload?.highest_seen_id === 'number' ? payload.highest_seen_id : 0;
		if (!port.trim() && typeof payload?.current_port === 'string' && payload.current_port) {
			port = payload.current_port;
		}
		if (previousCount === 0 && busServos.length > 0) {
			maybeAutoPromoteFactoryId();
		}
	}

	async function loadWaveshareInventory(options: { refresh?: boolean; silent?: boolean } = {}) {
		if (backend !== 'waveshare') return;
		const refresh = options.refresh === true;
		if (refresh && scanningBus) return;
		if (refresh) {
			scanningBus = true;
		}
		if (!options.silent) {
			errorMsg = null;
		}
		try {
			const url = new URL(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/${refresh ? 'rescan' : 'status'}`
			);
			if (port.trim()) {
				url.searchParams.set('port', port.trim());
			}
			const res = await fetch(url.toString(), { method: refresh ? 'POST' : 'GET' });
			if (!res.ok) throw new Error(await res.text());
			applyWaveshareInventory(await res.json());
		} catch (e: any) {
			if (!options.silent) {
				errorMsg = e.message ?? 'Failed to scan Waveshare bus';
			}
		} finally {
			if (refresh) {
				scanningBus = false;
			}
		}
	}

	async function scanBus(options: { silent?: boolean } = {}) {
		await loadWaveshareInventory({ refresh: true, silent: options.silent });
	}

	function maybeAutoPromoteFactoryId() {
		if (suggestedNextId === null) return;
		const target = suggestedNextId;
		const candidate = busServos.find((s) => s.id === 1);
		if (!candidate) return;
		// Avoid re-promoting the same id repeatedly if the backend still reports it briefly.
		if (autoPromotedIds.has(1)) return;
		if (busyByServoId[1]) return;
		autoPromotedIds = new Set([...autoPromotedIds, 1]);
		void promoteServoId(1, target).finally(() => {
			// Allow another auto-promotion cycle for a freshly-connected factory servo.
			setTimeout(() => {
				autoPromotedIds = new Set([...autoPromotedIds].filter((id) => id !== 1));
			}, 1500);
		});
	}

	function setBusy(servoId: number, kind: string | null) {
		if (kind === null) {
			const next = { ...busyByServoId };
			delete next[servoId];
			busyByServoId = next;
		} else {
			busyByServoId = { ...busyByServoId, [servoId]: kind };
		}
	}

	async function calibrateServo(servoId: number, force = false) {
		setBusy(servoId, 'calibrating');
		errorMsg = null;
		statusMsg = '';
		try {
			const query = force ? '?force=true' : '';
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos/${servoId}/calibrate${query}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				const text = await res.text();
				let detail = text || `Failed to calibrate servo ${servoId}`;
				try {
					const payload = JSON.parse(text);
					detail = payload?.detail ?? detail;
				} catch {
					// Keep the raw response body when the backend did not return JSON.
				}
				throw new Error(detail);
			}
			const payload = await res.json();
			statusMsg = payload?.message ?? `Servo ${servoId} calibrated.`;
			await loadWaveshareInventory({ refresh: true });
		} catch (e: any) {
			errorMsg = e.message ?? `Failed to calibrate servo ${servoId}`;
		} finally {
			setBusy(servoId, null);
		}
	}

	async function moveServo(servoId: number, position: 'open' | 'close' | 'center') {
		setBusy(servoId, 'moving');
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos/${servoId}/move`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ position })
				}
			);
			if (!res.ok) {
				const text = await res.text();
				throw new Error(text);
			}
			lastMoveByServoId = { ...lastMoveByServoId, [servoId]: position };
		} catch (e: any) {
			errorMsg = e.message ?? `Failed to move servo ${servoId}`;
		} finally {
			setBusy(servoId, null);
		}
	}

	async function toggleOpenClose(servoId: number) {
		const last = lastMoveByServoId[servoId] ?? 'close';
		await moveServo(servoId, last === 'open' ? 'close' : 'open');
	}

	async function nudgeLayer(layerIdx: number, degrees: number) {
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/servo/layers/${layerIdx - 1}/nudge`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ degrees })
				}
			);
			if (!res.ok) {
				const text = await res.text();
				throw new Error(text);
			}
			const data = await res.json();
			if (typeof data.new_angle === 'number') {
				estimatedAngleByLayer = { ...estimatedAngleByLayer, [layerIdx]: Math.round(data.new_angle) };
			}
		} catch (e: any) {
			errorMsg = e.message ?? `Failed to nudge layer ${layerIdx} servo`;
		}
	}

	async function nudgeServo(servoId: number, degrees: number) {
		setBusy(servoId, 'moving');
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos/${servoId}/nudge`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ degrees })
				}
			);
			if (!res.ok) {
				const text = await res.text();
				throw new Error(text);
			}
			const data = await res.json();
			if (typeof data.raw_position === 'number' && data.limits) {
				busServos = busServos.map(s => s.id === servoId ? { ...s, position: data.raw_position } : s);
			}
		} catch (e: any) {
			errorMsg = e.message ?? `Failed to nudge servo ${servoId}`;
		} finally {
			setBusy(servoId, null);
		}
	}

	async function promoteServoId(currentId: number, newId: number) {
		setBusy(currentId, 'promoting');
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos/${currentId}/set-id`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ new_id: newId })
				}
			);
			if (!res.ok) {
				const text = await res.text();
				throw new Error(text);
			}
			const payload = await res.json();
			// Move any existing layer assignment from old id to new id.
			if (layerByAssignment[currentId] !== undefined) {
				const layer = layerByAssignment[currentId];
				const next = { ...layerByAssignment };
				delete next[currentId];
				next[newId] = layer;
				layerByAssignment = next;
			}
			statusMsg = payload?.message ?? `Servo ${currentId} → ${newId}.`;
			await loadWaveshareInventory({ refresh: true });
		} catch (e: any) {
			errorMsg = e.message ?? `Failed to change servo ID`;
		} finally {
			setBusy(currentId, null);
		}
	}

	function assignLayer(servoId: number, layerIndex: number) {
		const next = { ...layerByAssignment };
		// Clear any other servo previously bound to this layer.
		for (const [key, value] of Object.entries(next)) {
			if (value === layerIndex && Number(key) !== servoId) {
				delete next[Number(key)];
			}
		}
		if (layerIndex === 0) {
			delete next[servoId];
		} else {
			next[servoId] = layerIndex;
		}
		layerByAssignment = next;
	}

	function assignedServoForLayer(layerIndex: number): number | null {
		for (const [servoIdStr, assignedLayer] of Object.entries(layerByAssignment)) {
			if (assignedLayer === layerIndex) {
				const servoId = Number(servoIdStr);
				if (backend === 'waveshare' && (servoId < 1 || servoId > 253)) return null;
				return servoId;
			}
		}
		return null;
	}

	function setStorageLayer(layerIndex: number, patch: Partial<StorageLayerDraft>) {
		storageLayers = storageLayers.map((layer, index) =>
			index + 1 === layerIndex ? { ...layer, ...patch } : layer
		);
	}

	function addStorageLayer() {
		storageLayers = [
			...storageLayers,
			{
				bin_count: allowedBinCounts[0] ?? 12,
				enabled: true,
				max_pieces_per_bin: null,
				max_dimension_mm: null
			}
		];
		layerCount = storageLayers.length;
	}

	function removeStorageLayer(layerIndex: number) {
		if (storageLayers.length <= 1) return;
		storageLayers = storageLayers.filter((_, index) => index + 1 !== layerIndex);
		layerCount = storageLayers.length;

		const nextAssignments: Record<number, number> = {};
		for (const [servoIdStr, assignedLayer] of Object.entries(layerByAssignment)) {
			if (assignedLayer === layerIndex) continue;
			nextAssignments[Number(servoIdStr)] = assignedLayer > layerIndex ? assignedLayer - 1 : assignedLayer;
		}
		layerByAssignment = nextAssignments;

		const nextInverts: Record<number, boolean> = {};
		const nextOpenAngles: Record<number, string> = {};
		const nextClosedAngles: Record<number, string> = {};
		const nextEstimatedAngles: Record<number, number> = {};
		for (let oldLayer = 1; oldLayer <= layerCount + 1; oldLayer++) {
			if (oldLayer === layerIndex) continue;
			const newLayer = oldLayer > layerIndex ? oldLayer - 1 : oldLayer;
			if (invertByLayer[oldLayer] !== undefined) nextInverts[newLayer] = invertByLayer[oldLayer];
			if (openAngleByLayer[oldLayer] !== undefined) {
				nextOpenAngles[newLayer] = openAngleByLayer[oldLayer];
			}
			if (closedAngleByLayer[oldLayer] !== undefined) {
				nextClosedAngles[newLayer] = closedAngleByLayer[oldLayer];
			}
			if (estimatedAngleByLayer[oldLayer] !== undefined) {
				nextEstimatedAngles[newLayer] = estimatedAngleByLayer[oldLayer];
			}
		}
		invertByLayer = nextInverts;
		openAngleByLayer = nextOpenAngles;
		closedAngleByLayer = nextClosedAngles;
		estimatedAngleByLayer = nextEstimatedAngles;
		if (selectedLayerIdx === layerIndex) selectedLayerIdx = null;
		if (selectedLayerIdx !== null && selectedLayerIdx > layerIndex) selectedLayerIdx -= 1;
	}

	function setInvertForLayer(layerIndex: number, invert: boolean) {
		invertByLayer = { ...invertByLayer, [layerIndex]: invert };
	}

	function usedLayersForBusServos(): Set<number> {
		// Only count an assignment as "occupying" a layer if the servo it
		// points at is actually present on the bus right now. Otherwise stale
		// entries from a previous save (e.g. before promoting an ID 1 servo)
		// keep hogging slots and the dropdown looks empty.
		const onBus = new Set(busServos.map((s) => s.id));
		const used = new Set<number>();
		for (const [servoIdStr, layerIdx] of Object.entries(layerByAssignment)) {
			if (onBus.size === 0 || onBus.has(Number(servoIdStr))) {
				used.add(layerIdx);
			}
		}
		return used;
	}

	function unassignedLayers(currentLayer: number): number[] {
		const used = usedLayersForBusServos();
		const result: number[] = [];
		for (let i = 1; i <= layerCount; i++) {
			if (!used.has(i) || i === currentLayer) {
				result.push(i);
			}
		}
		return result;
	}

	function toggleInvertForLayer(layerIndex: number) {
		invertByLayer = {
			...invertByLayer,
			[layerIndex]: !Boolean(invertByLayer[layerIndex])
		};
	}

	function buildChannelsForSave(): Array<{ id: number | null; invert: boolean }> {
		const channels: Array<{ id: number | null; invert: boolean }> = [];
		// Build a layer → servoId map, but only honour assignments that
		// still point at a servo currently on the bus (when we have a bus).
		const onBus = new Set(busServos.map((s) => s.id));
		const servoByLayer: Record<number, number> = {};
		for (const [servoIdStr, layerIdx] of Object.entries(layerByAssignment)) {
			const servoId = Number(servoIdStr);
			if (onBus.size > 0 && !onBus.has(servoId)) continue;
			servoByLayer[layerIdx] = servoId;
		}
		const upper = layerCount;
		for (let layer = 1; layer <= upper; layer++) {
			const id = servoByLayer[layer] ?? (backend === 'waveshare' ? null : layer - 1);
			channels.push({
				id,
				invert: Boolean(invertByLayer[layer])
			});
		}
		return channels;
	}

	function buildStorageLayersForSave() {
		const result: Array<{
			bin_count: number;
			enabled: boolean;
			servo_open_angle: number | null;
			servo_closed_angle: number | null;
			max_pieces_per_bin: number | null;
			max_dimension_mm: number | null;
		}> = [];
		for (let i = 0; i < layerCount; i++) {
			const sl = storageLayers[i];
			const openStr = openAngleByLayer[i + 1] ?? '';
			const closedStr = closedAngleByLayer[i + 1] ?? '';
			const openVal = openStr !== '' ? Number(openStr) : null;
			const closedVal = closedStr !== '' ? Number(closedStr) : null;
			result.push({
				bin_count: sl?.bin_count ?? 12,
				enabled: sl?.enabled ?? true,
				servo_open_angle: openVal !== null && Number.isFinite(openVal) ? openVal : null,
				servo_closed_angle: closedVal !== null && Number.isFinite(closedVal) ? closedVal : null,
				max_pieces_per_bin: sl?.max_pieces_per_bin ?? null,
				max_dimension_mm: sl?.max_dimension_mm ?? null
			});
		}
		return result;
	}

	async function saveServoSetup() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const channels = buildChannelsForSave();

			const storageLayers = buildStorageLayersForSave();
			if (backend === 'waveshare') {
				for (let index = 0; index < storageLayers.length; index++) {
					if (storageLayers[index].enabled && channels[index]?.id === null) {
						throw new Error(
							`Layer ${index + 1} is active but has no detected servo assigned. Assign a servo, disable the layer, or remove it.`
						);
					}
				}
			}
			const storageRes = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/storage-layers`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layers: storageLayers })
			});
			if (!storageRes.ok) throw new Error(await storageRes.text());

			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/servo`, {
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
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			statusMsg = payload?.message ?? 'Servo setup saved.';
			await loadSettings();
			if (onSaved) {
				await onSaved();
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save servo setup';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		if (machineKey === loadedMachineKey) return;
		loadedMachineKey = machineKey;
		void loadSettings();
	});

	$effect(() => {
		const desired = servoSource === 'waveshare' ? 'waveshare' : 'pca9685';
		if (backend === desired) return;
		backend = desired;
		if (desired === 'waveshare') {
			void loadWaveshareInventory({ refresh: false, silent: true });
		} else {
			busServos = [];
		}
	});

	onMount(() => {
		const interval = setInterval(() => {
			if (backend !== 'waveshare') return;
			// Skip auto-refresh while a per-servo action is running so we don't fight it.
			if (Object.keys(busyByServoId).length > 0) return;
			if (scanningBus) return;
			void loadWaveshareInventory({ refresh: false, silent: true });
		}, 4000);

		function handleKeydown(e: KeyboardEvent) {
			if (selectedServoId === null && selectedLayerIdx === null) return;
			if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
			if (e.key === 'ArrowLeft') {
				e.preventDefault();
				if (selectedServoId !== null) void nudgeServo(selectedServoId, -nudgeDegrees);
				else if (selectedLayerIdx !== null) void nudgeLayer(selectedLayerIdx, -nudgeDegrees);
			} else if (e.key === 'ArrowRight') {
				e.preventDefault();
				if (selectedServoId !== null) void nudgeServo(selectedServoId, nudgeDegrees);
				else if (selectedLayerIdx !== null) void nudgeLayer(selectedLayerIdx, nudgeDegrees);
			} else if (e.key === 'Escape') {
				selectedServoId = null;
				selectedLayerIdx = null;
			}
		}
		window.addEventListener('keydown', handleKeydown);

		return () => {
			clearInterval(interval);
			window.removeEventListener('keydown', handleKeydown);
		};
	});
</script>

<div class="flex flex-col gap-4">
	<div class="setup-panel px-4 py-3 text-sm text-text-muted">
		Discover the servos on the bus, calibrate each one's open/close range, then assign each to a
		storage layer. Tip: connect one new servo at a time so its factory ID 1 doesn't clash with the
		others — promote it to a fresh ID before connecting the next.
	</div>

	{#if !settingsLoaded}
		{#if errorMsg}
			<div class="setup-panel border border-danger bg-primary-light px-4 py-4 text-sm text-[#7A0A0B]">
				<div class="font-medium">Failed to load servo configuration</div>
				<div class="mt-1">{errorMsg}</div>
				<button
					onclick={() => void loadSettings()}
					class="mt-3 border border-danger px-3 py-1.5 text-sm font-medium text-[#7A0A0B] transition-colors hover:bg-danger/10"
				>
					Retry
				</button>
			</div>
		{:else}
			<div class="setup-panel px-4 py-6 text-center text-sm text-text-muted">
				Loading servo configuration…
			</div>
		{/if}
	{:else}
	<div class="setup-panel p-4">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<div class="text-sm font-semibold text-text">Servo backend</div>
				{#if servoSource === 'waveshare'}
					<div class="mt-1 text-sm text-text-muted">
						{#if discoveredServoSource === 'waveshare'}
							Waveshare SC serial bus auto-detected from discovery
							{#if discoveredWaveshareServos > 0}
								— <span class="text-text">{discoveredWaveshareServos} servo{discoveredWaveshareServos === 1 ? '' : 's'}</span> on the bus.
							{:else}
								.
							{/if}
						{:else}
							Using the Waveshare SC serial bus.
						{/if}
					</div>
				{:else}
					<div class="mt-1 text-sm text-text-muted">
						No Waveshare servo bus detected — assuming PCA9685 on a control board.
					</div>
				{/if}
			</div>
			{#if discoveredServoSource !== servoSource && onSourceChange}
				<button
					type="button"
					onclick={() => onSourceChange(discoveredServoSource)}
					class="setup-button-secondary px-3 py-1.5 text-sm text-text whitespace-nowrap"
				>
					Use detected ({discoveredServoSource === 'waveshare' ? 'Waveshare' : 'PCA9685'})
				</button>
			{/if}
		</div>
	</div>

	{#if servoSource === 'waveshare'}
		<SerialPortPanel
			bind:port
			{availablePorts}
			{loadingPorts}
			onLoadPorts={loadPorts}
			onScan={() => scanBus()}
		/>

		<div class="setup-panel p-4">
			<div class="flex flex-wrap items-start justify-between gap-3">
				<div class="min-w-0">
					<div class="text-sm font-semibold text-text">Storage layers</div>
					<div class="mt-1 text-sm text-text-muted">
						{storageLayers.length} configured · {activeLayerCount} active · {assignedLayerCount}
						assigned · {busServos.length} detected servo{busServos.length === 1 ? '' : 's'}
					</div>
				</div>
				<button
					type="button"
					onclick={addStorageLayer}
					disabled={saving || loading}
					class="setup-button-secondary inline-flex min-h-10 items-center gap-2 px-3 py-2 text-sm font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
				>
					<Plus size={15} /> Add layer
				</button>
			</div>

			{#if activeLayerCount > busServos.length}
				<div class="mt-3 border border-warning bg-[#FFF7E0] px-3 py-2 text-sm text-[#7A5A00]">
					There are more active layers than detected servos. Assign more servos, disable unused
					layers, or remove them before saving.
				</div>
			{/if}

			{#if storageLayers.length === 0}
				<div class="mt-4 border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
					No storage layers configured.
				</div>
			{:else}
				<div class="mt-4 grid gap-2">
					{#each storageLayers as layer, index}
						{@const layerIndex = index + 1}
						{@const assignedServoId = assignedServoForLayer(layerIndex)}
						{@const assignedServoPresent =
							assignedServoId !== null && busServos.some((servo) => servo.id === assignedServoId)}
						<div
							class="grid gap-3 border border-border bg-bg/40 px-3 py-3 md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-center"
						>
							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-2">
									<span class="text-sm font-semibold text-text">Layer {layerIndex}</span>
									<span
										class={`px-2 py-0.5 text-xs font-medium ${layer.enabled ? 'bg-success/10 text-success' : 'bg-surface text-text-muted'}`}
									>
										{layer.enabled ? 'Active' : 'Inactive'}
									</span>
								</div>
								<div class="mt-1 text-sm text-text-muted">
									{#if assignedServoId === null}
										No servo assigned
									{:else if assignedServoPresent}
										Servo ID {assignedServoId}
									{:else}
										Servo ID {assignedServoId} not detected
									{/if}
								</div>
							</div>

							<label class="inline-flex min-h-10 items-center gap-2 text-sm text-text">
								<input
									class="setup-toggle"
									type="checkbox"
									checked={layer.enabled}
									onchange={(event) =>
										setStorageLayer(layerIndex, { enabled: event.currentTarget.checked })}
									disabled={saving || loading}
								/>
								Active
							</label>

							<label class="inline-flex min-h-10 items-center gap-2 text-sm text-text-muted">
								Bins
								<select
									value={String(layer.bin_count)}
									onchange={(event) =>
										setStorageLayer(layerIndex, { bin_count: Number(event.currentTarget.value) })}
									disabled={saving || loading}
									class="setup-control w-20 px-2 py-1 text-text"
								>
									{#each allowedBinCounts as count}
										<option value={String(count)}>{count}</option>
									{/each}
								</select>
							</label>

							<button
								type="button"
								onclick={() => removeStorageLayer(layerIndex)}
								disabled={saving || loading || storageLayers.length <= 1}
								class="inline-flex min-h-10 items-center justify-center border border-danger/30 bg-danger/[0.06] px-3 py-2 text-danger transition-colors hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
								title="Remove Layer {layerIndex}"
							>
								<Trash2 size={15} />
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<ServoInventoryList
			{busServos}
			{highestSeenId}
			{suggestedNextId}
			bind:selectedServoId
			{busyByServoId}
			{lastMoveByServoId}
			{openAngle}
			{closedAngle}
			bind:openAngleByLayer
			bind:closedAngleByLayer
			bind:nudgeDegrees
			{servoSetupState}
			{unassignedLayers}
			onAssignLayer={assignLayer}
			onPromote={(servoId) => promoteServoId(servoId, suggestedNextId!)}
			onCalibrate={(servoId, force) => calibrateServo(servoId, force)}
			onToggleOpenClose={toggleOpenClose}
			onToggleInvert={toggleInvertForLayer}
			onNudge={(servoId, degrees) => void nudgeServo(servoId, degrees)}
		/>
	{:else}
		<ServoLayerCalibrator showDirections />
	{/if}

	<div class="flex flex-wrap items-center gap-3">
		<button
			onclick={saveServoSetup}
			disabled={saving}
			class="border border-success bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-60"
		>
			{saving ? 'Saving…' : 'Save servo setup'}
		</button>
		{#if loading}
			<div class="text-sm text-text-muted">Loading current servo configuration…</div>
		{/if}
	</div>

	{#if servoIssues.length}
		<div
			class="border border-danger bg-primary-light px-4 py-3 text-sm text-[#7A0A0B]"
		>
			{#each servoIssues as issue}
				<div>{issue.message}</div>
			{/each}
		</div>
	{/if}

	{#if errorMsg}
		<div
			class="border border-danger bg-primary-light px-4 py-3 text-sm text-[#7A0A0B]"
		>
			{errorMsg}
		</div>
	{:else if statusMsg}
		<div
			class="border border-success bg-[#D4EDDA] px-4 py-3 text-sm font-medium text-success"
		>
			{statusMsg}
		</div>
	{/if}
	{/if}
</div>
