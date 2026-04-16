<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';
	import SerialPortPanel from './servo/SerialPortPanel.svelte';
	import ServoInventoryList from './servo/ServoInventoryList.svelte';
	import PcaChannelMapping from './servo/PcaChannelMapping.svelte';

	type ServoBackend = 'pca9685' | 'waveshare';

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

	let {
		onSaved = null
	}: {
		onSaved?: (() => void | Promise<void>) | null;
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
	let storageLayers = $state<Array<{ bin_count: number; enabled: boolean }>>([]);
	// servoId → layer index (1-based). For PCA, channelId → layer index.
	let layerByAssignment = $state<Record<number, number>>({});
	// per-layer invert (1-based layer index → invert)
	let invertByLayer = $state<Record<number, boolean>>({});

	// per-layer angle overrides (1-based layer index → angle or empty string for "use global")
	let openAngleByLayer = $state<Record<number, string>>({});
	let closedAngleByLayer = $state<Record<number, string>>({});

	// per-servo UI state
	let busyByServoId = $state<Record<number, string>>({}); // 'calibrating' | 'moving' | 'promoting'
	let lastMoveByServoId = $state<Record<number, 'open' | 'close' | 'center'>>({});
	// Track servo ids we've already auto-promoted this session so we don't loop.
	let autoPromotedIds = $state<Set<number>>(new Set());

	let selectedServoId = $state<number | null>(null);
	let selectedLayerIdx = $state<number | null>(null);
	let nudgeDegrees = $state<number>(5);

	// Effective number of assignable layers. If we have more servos on the bus
	// than the configured storage layers, expand so every servo can be mapped.
	const effectiveLayerCount = $derived(Math.max(layerCount, busServos.length));

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function pcaChoices(): number[] {
		return availableServoIds.length > 0
			? availableServoIds
			: Array.from({ length: Math.max(layerCount, 1) }, (_, index) => index);
	}

	function servoSetupState(servo: BusServo) {
		const calibrated =
			typeof servo.min_limit === 'number' &&
			typeof servo.max_limit === 'number' &&
			(servo.max_limit ?? 0) - (servo.min_limit ?? 0) >= 20;
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

		backend = servo.backend === 'waveshare' ? 'waveshare' : 'pca9685';
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

		layerCount = Math.max(storageLayersRaw.length, Number(servo.layer_count ?? 0));
		storageLayers = storageLayersRaw.map((sl: any) => ({
			bin_count: Number(sl?.bin_count ?? 12),
			enabled: sl?.enabled !== false,
		}));

		const newAssignments: Record<number, number> = {};
		const newInverts: Record<number, boolean> = {};
		for (let i = 0; i < layerCount; i++) {
			const channel = servoChannels[i];
			if (channel && typeof channel.id === 'number') {
				newAssignments[channel.id] = i + 1;
				newInverts[i + 1] = Boolean(channel.invert);
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

	async function calibrateServo(servoId: number) {
		setBusy(servoId, 'calibrating');
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos/${servoId}/calibrate`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				const text = await res.text();
				throw new Error(text);
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
		for (let i = 1; i <= effectiveLayerCount; i++) {
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

	function buildChannelsForSave(): Array<{ id: number; invert: boolean }> {
		const channels: Array<{ id: number; invert: boolean }> = [];
		// Build a layer → servoId map, but only honour assignments that
		// still point at a servo currently on the bus (when we have a bus).
		const onBus = new Set(busServos.map((s) => s.id));
		const servoByLayer: Record<number, number> = {};
		for (const [servoIdStr, layerIdx] of Object.entries(layerByAssignment)) {
			const servoId = Number(servoIdStr);
			if (onBus.size > 0 && !onBus.has(servoId)) continue;
			servoByLayer[layerIdx] = servoId;
		}
		const upper = Math.max(layerCount, effectiveLayerCount);
		for (let layer = 1; layer <= upper; layer++) {
			const id =
				servoByLayer[layer] ?? (backend === 'waveshare' ? layer : layer - 1);
			channels.push({
				id,
				invert: Boolean(invertByLayer[layer])
			});
		}
		return channels;
	}

	function buildStorageLayersForSave() {
		const result: Array<{ bin_count: number; enabled: boolean; servo_open_angle: number | null; servo_closed_angle: number | null }> = [];
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
		<div class="setup-panel px-4 py-6 text-center text-sm text-text-muted">
			Loading servo configuration…
		</div>
	{:else}
	<div class="setup-panel p-4">
		<div class="text-sm font-semibold text-text">Servo backend</div>
		<div class="mt-3 grid gap-3 sm:grid-cols-2">
			<label class="flex items-center gap-2 text-sm text-text">
				<input
					class="setup-toggle"
					type="radio"
					name="servo-backend"
					checked={backend === 'pca9685'}
					onchange={() => {
						backend = 'pca9685';
						busServos = [];
					}}
				/>
				<span>PCA9685 on a control board</span>
			</label>
			<label class="flex items-center gap-2 text-sm text-text">
				<input
					class="setup-toggle"
					type="radio"
					name="servo-backend"
					checked={backend === 'waveshare'}
					onchange={() => {
						backend = 'waveshare';
						void loadWaveshareInventory({ refresh: false, silent: true });
					}}
				/>
				<span>Waveshare SC serial bus</span>
			</label>
		</div>
	</div>

	{#if backend === 'waveshare'}
		<SerialPortPanel
			bind:port
			{availablePorts}
			{loadingPorts}
			onLoadPorts={loadPorts}
			onScan={() => scanBus()}
		/>

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
			onCalibrate={calibrateServo}
			onToggleOpenClose={toggleOpenClose}
			onToggleInvert={toggleInvertForLayer}
			onNudge={(servoId, degrees) => void nudgeServo(servoId, degrees)}
		/>
	{:else}
		<PcaChannelMapping
			{layerCount}
			pcaChoices={pcaChoices()}
			bind:layerByAssignment
			{invertByLayer}
			bind:openAngle
			bind:closedAngle
			bind:openAngleByLayer
			bind:closedAngleByLayer
			bind:nudgeDegrees
			{selectedLayerIdx}
			onSetInvert={setInvertForLayer}
			onNudgeLayer={(layerIdx, degrees) => void nudgeLayer(layerIdx, degrees)}
			onSelectLayer={(layerIdx) => {
				selectedLayerIdx = selectedLayerIdx === layerIdx ? null : layerIdx;
				selectedServoId = null;
			}}
		/>
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
