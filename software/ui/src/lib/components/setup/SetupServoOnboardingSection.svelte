<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';

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
				accent: 'border-l-[#F2A900]',
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
				accent: 'border-l-[#0055BF]',
				headerTone: 'bg-[#0055BF]/[0.06]',
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
			accent: 'border-l-[#00852B]',
			headerTone: 'bg-[#00852B]/[0.06]',
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
				void loadPorts();
				void scanBus({ silent: true });
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
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/waveshare/ports`);
			if (!res.ok) return;
			const payload = await res.json();
			availablePorts = Array.isArray(payload?.ports) ? payload.ports : [];
		} finally {
			loadingPorts = false;
		}
	}

	async function scanBus(options: { silent?: boolean } = {}) {
		if (backend !== 'waveshare') return;
		if (scanningBus) return;
		scanningBus = true;
		if (!options.silent) {
			errorMsg = null;
		}
		try {
			const url = new URL(`${currentBackendBaseUrl()}/api/hardware-config/waveshare/servos`);
			if (port.trim()) {
				url.searchParams.set('port', port.trim());
			}
			const res = await fetch(url.toString());
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			busServos = Array.isArray(payload?.servos) ? payload.servos : [];
			suggestedNextId =
				typeof payload?.suggested_next_id === 'number' ? payload.suggested_next_id : null;
			highestSeenId = typeof payload?.highest_seen_id === 'number' ? payload.highest_seen_id : 0;
			// Auto-promote any servo still on the factory ID 1 to the next free id,
			// so the user can just connect them one by one without a second click.
			maybeAutoPromoteFactoryId();
		} catch (e: any) {
			if (!options.silent) {
				errorMsg = e.message ?? 'Failed to scan Waveshare bus';
			}
		} finally {
			scanningBus = false;
		}
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
			await scanBus();
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
			await scanBus();
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
			void scanBus({ silent: true });
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
						void loadPorts();
						void scanBus();
					}}
				/>
				<span>Waveshare SC serial bus</span>
			</label>
		</div>
	</div>

	{#if backend === 'waveshare'}
		<div class="setup-panel p-4">
			<div class="text-sm font-semibold text-text">Serial port</div>
			<div class="mt-3 grid gap-3 sm:grid-cols-[2fr_auto_auto]">
				<select bind:value={port} class="setup-control px-3 py-2 text-text">
					<option value="">Auto detect / current selection</option>
					{#each availablePorts as candidate}
						<option value={candidate.device}>
							{candidate.device} · {candidate.product}
						</option>
					{/each}
				</select>
				<button
					onclick={loadPorts}
					disabled={loadingPorts}
					class="setup-button-secondary px-3 py-2 text-sm text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
				>
					{loadingPorts ? 'Refreshing…' : 'Refresh ports'}
				</button>
				<button
					onclick={() => scanBus()}
					class="border border-[#0055BF] bg-[#0055BF] px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-[#0055BF]/90"
				>
					Scan bus
				</button>
			</div>
		</div>

		<div class="setup-panel p-4">
			<div>
				<div class="text-sm font-semibold text-text">Detected servos</div>
				<div class="mt-1 text-xs text-text-muted">
					{busServos.length} on the bus · highest ID ever seen: {highestSeenId || '–'}
					{#if suggestedNextId !== null}
						· next free ID: {suggestedNextId}
					{/if}
				</div>
			</div>

			{#if busServos.length === 0}
				<div class="mt-4 border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
					No servos found yet. Connect your first servo — the bus auto-scans every few seconds.
				</div>
			{:else}
				<div class="mt-4 grid gap-3">
					{#each busServos as servo (servo.id)}
						{@const busy = busyByServoId[servo.id]}
						{@const setup = servoSetupState(servo)}
						{@const calibrated = setup.calibrated}
						{@const layer = setup.layer}
						{@const lastMove = lastMoveByServoId[servo.id]}
						{@const inverted = setup.inverted}
						{@const isFactory = setup.isFactory}
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class={`overflow-hidden border border-l-4 bg-surface ${setup.accent} ${selectedServoId === servo.id ? 'border-[#0055BF] ring-2 ring-[#0055BF]/30' : 'border-border'}`}
							onclick={() => { selectedServoId = selectedServoId === servo.id ? null : servo.id; }}
						>
							<div class={`flex flex-wrap items-start gap-4 px-4 py-3 ${setup.headerTone}`}>
								<div
									class="flex h-12 w-14 shrink-0 flex-col items-center justify-center bg-[#0055BF] font-bold text-white"
								>
									<span class="text-[10px] uppercase tracking-wider opacity-80">ID</span>
									<span class="text-base leading-none">{servo.id}</span>
								</div>

								<div class="min-w-0 flex-1">
									<div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
										<span class="text-sm font-semibold text-text">
											{servo.model_name ?? 'Unknown model'}
										</span>
										{#if servo.voltage !== null && servo.voltage !== undefined}
											<span class="text-xs text-text-muted">{servo.voltage} V</span>
										{/if}
									</div>
									<div class="mt-1 text-sm font-semibold text-text">{setup.title}</div>
									<div class="mt-1 text-xs text-text-muted">{setup.description}</div>
								</div>

								<div class="min-w-[11rem] sm:ml-auto">
									<label class="flex flex-col gap-1">
										<span class="text-[10px] uppercase tracking-wider text-text-muted">Assigned to</span>
										<select
											value={String(layer)}
											onchange={(event) =>
												assignLayer(
													servo.id,
													Number((event.currentTarget as HTMLSelectElement).value)
												)}
											class="setup-control w-full px-3 py-2 text-sm font-medium text-text"
										>
											<option value="0">— Unassigned —</option>
											{#each unassignedLayers(layer) as layerOption}
												<option value={String(layerOption)}>Layer {layerOption}</option>
											{/each}
										</select>
									</label>
								</div>
							</div>

							<div class="grid gap-3 border-t border-border px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
								<div>
									<div class="text-[10px] uppercase tracking-wider text-text-muted">Setup checklist</div>
									<div class="mt-2 flex flex-wrap gap-2 text-xs">
										<span class={`inline-flex items-center gap-1 border px-2 py-1 font-medium ${calibrated ? 'border-[#0055BF]/30 bg-[#0055BF]/10 text-[#0055BF]' : 'border-border bg-bg text-text-muted'}`}>
											<span class={`h-1.5 w-1.5 rounded-full ${calibrated ? 'bg-[#0055BF]' : 'bg-text-muted'}`}></span>
											{calibrated ? `Calibrated · ${servo.min_limit}–${servo.max_limit}` : 'Calibration pending'}
										</span>
										<span class={`inline-flex items-center gap-1 border px-2 py-1 font-medium ${layer > 0 ? 'border-[#00852B]/30 bg-[#00852B]/10 text-[#00852B]' : 'border-border bg-bg text-text-muted'}`}>
											<span class={`h-1.5 w-1.5 rounded-full ${layer > 0 ? 'bg-[#00852B]' : 'bg-text-muted'}`}></span>
											{layer > 0 ? `Assigned · Layer ${layer}` : 'Layer not assigned'}
										</span>
										<span class={`inline-flex items-center gap-1 border px-2 py-1 font-medium ${layer > 0 ? 'border-border bg-bg text-text' : 'border-border bg-bg text-text-muted'}`}>
											<span class={`h-1.5 w-1.5 rounded-full ${layer > 0 ? 'bg-text' : 'bg-text-muted'}`}></span>
											Direction {layer > 0 ? (inverted ? 'reversed' : 'normal') : 'set after assignment'}
										</span>
									</div>
								</div>

								{#if isFactory}
									<div class="border border-[#F2A900]/40 bg-[#FFF7E0] px-3 py-2 text-xs text-[#7A5A00] md:max-w-[18rem]">
										<div class="font-semibold text-[#5C4400]">Factory ID detected</div>
										<div class="mt-1">Promote this servo before plugging in the next one.</div>
										<button
											onclick={() => promoteServoId(servo.id, suggestedNextId!)}
											disabled={!!busy}
											class="mt-2 border border-[#F2A900] bg-[#F2A900] px-3 py-1.5 text-xs font-semibold text-[#3D2A00] transition-colors hover:bg-[#F2A900]/90 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{busy === 'promoting' ? 'Promoting…' : `Promote to ID ${suggestedNextId}`}
										</button>
									</div>
								{/if}
							</div>

							{#if layer > 0}
								<div class="border-t border-border bg-bg/40 px-4 py-3">
									<div class="text-[10px] uppercase tracking-wider text-text-muted">Angle overrides for Layer {layer}</div>
									<div class="mt-2 grid gap-3 sm:grid-cols-2 max-w-sm">
										<label class="flex flex-col gap-1 text-xs text-text-muted">
											<span>Open angle (°)</span>
											<input
												type="number"
												min="0"
												max="180"
												placeholder={String(openAngle)}
												value={openAngleByLayer[layer] ?? ''}
												oninput={(event) => {
													const val = (event.currentTarget as HTMLInputElement).value;
													openAngleByLayer = { ...openAngleByLayer, [layer]: val };
												}}
												class="setup-control px-2 py-1.5 text-text"
											/>
										</label>
										<label class="flex flex-col gap-1 text-xs text-text-muted">
											<span>Closed angle (°)</span>
											<input
												type="number"
												min="0"
												max="180"
												placeholder={String(closedAngle)}
												value={closedAngleByLayer[layer] ?? ''}
												oninput={(event) => {
													const val = (event.currentTarget as HTMLInputElement).value;
													closedAngleByLayer = { ...closedAngleByLayer, [layer]: val };
												}}
												class="setup-control px-2 py-1.5 text-text"
											/>
										</label>
									</div>
									<div class="mt-1 text-[10px] text-text-muted">Leave blank to use the default angles ({openAngle}° / {closedAngle}°)</div>
								</div>
							{/if}

							<div class="border-t border-border bg-bg/40 px-4 py-3">
								<div class="text-[10px] uppercase tracking-wider text-text-muted">Actions</div>
								<div class="mt-2 flex flex-wrap items-center gap-2">
									<button
										onclick={() => calibrateServo(servo.id)}
										disabled={!!busy}
										class={`px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${calibrated ? 'setup-button-secondary text-text' : 'border border-[#0055BF] bg-[#0055BF] text-white hover:bg-[#0055BF]/90'}`}
									>
										{busy === 'calibrating'
											? 'Calibrating…'
											: calibrated
												? 'Recalibrate'
												: 'Auto-calibrate'}
									</button>
									<button
										onclick={() => toggleOpenClose(servo.id)}
										disabled={!!busy || !calibrated}
										class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										{busy === 'moving'
											? 'Testing…'
											: lastMove === 'open'
												? 'Test close'
												: 'Test open'}
									</button>
									<button
										onclick={() => toggleInvertForLayer(layer)}
										disabled={!calibrated || layer === 0}
										title={layer === 0
											? 'Assign a layer first to remember this direction change'
											: 'Use this if the gate opens when it should close'}
										class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
									>
										{inverted ? 'Direction reversed' : 'Reverse direction'}
									</button>
								</div>

								{#if calibrated}
									<div class="mt-3 flex items-center gap-2">
										<span class="text-[10px] uppercase tracking-wider text-text-muted">Nudge</span>
										<button
											onclick={(e) => { e.stopPropagation(); void nudgeServo(servo.id, -nudgeDegrees); }}
											disabled={!!busy}
											class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-60"
											title="Move left"
										>
											<ChevronLeft size={16} />
										</button>
										<input
											type="number"
											min="1"
											max="180"
											bind:value={nudgeDegrees}
											onclick={(e) => e.stopPropagation()}
											class="setup-control w-14 px-2 py-1 text-center text-xs text-text"
										/>
										<span class="text-[10px] text-text-muted">°</span>
										<button
											onclick={(e) => { e.stopPropagation(); void nudgeServo(servo.id, nudgeDegrees); }}
											disabled={!!busy}
											class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-60"
											title="Move right"
										>
											<ChevronRight size={16} />
										</button>
										{#if selectedServoId === servo.id}
											<span class="text-[10px] text-[#0055BF]">Selected — use ←/→ arrow keys</span>
										{:else}
											<span class="text-[10px] text-text-muted">Click card to use arrow keys</span>
										{/if}
									</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Persistent help: connect one at a time -->
			<div
				class="mt-4 border border-[#F2A900] bg-[#FFF7E0] px-4 py-3 text-xs leading-relaxed text-[#7A5A00]"
			>
				<div class="font-semibold text-[#5C4400]">Connect one servo at a time</div>
				<div class="mt-1">
					Brand-new Waveshare servos all ship with the factory ID <span class="font-semibold">1</span>,
					and the bus can only talk to one device at that ID. Plug servos in one by one — as soon
					as a fresh one shows up, we automatically promote it to the next free ID
					{#if suggestedNextId !== null}
						(currently <span class="font-semibold">{suggestedNextId}</span>)
					{/if}
					so you can connect the next servo without a collision.
				</div>
			</div>
		</div>
	{:else}
		<div class="setup-panel p-4">
			<div class="text-sm font-semibold text-text">Default open/close angles</div>
			<div class="mt-1 text-xs text-text-muted">
				Default angles used for layers that don't have a custom override set below.
			</div>
			<div class="mt-3 grid gap-3 sm:grid-cols-2">
				<label class="flex flex-col gap-1 text-xs text-text-muted">
					<span>Open angle (°)</span>
					<input
						type="number"
						min="0"
						max="180"
						bind:value={openAngle}
						class="setup-control px-3 py-2 text-text"
					/>
				</label>
				<label class="flex flex-col gap-1 text-xs text-text-muted">
					<span>Closed angle (°)</span>
					<input
						type="number"
						min="0"
						max="180"
						bind:value={closedAngle}
						class="setup-control px-3 py-2 text-text"
					/>
				</label>
			</div>
		</div>

		<div class="setup-panel p-4">
			<div class="text-sm font-semibold text-text">PCA9685 channel mapping</div>
			<div class="mt-1 text-sm text-text-muted">
				Available channels: {pcaChoices().join(', ')}
			</div>
			<div class="mt-4 overflow-x-auto">
				<table class="min-w-full border-collapse text-sm">
					<thead>
						<tr class="border-b border-border text-left text-text-muted">
							<th class="px-3 py-2 font-medium">Layer</th>
							<th class="px-3 py-2 font-medium">Channel</th>
							<th class="px-3 py-2 font-medium">Invert</th>
							<th class="px-3 py-2 font-medium">Open °</th>
							<th class="px-3 py-2 font-medium">Closed °</th>
								<th class="px-3 py-2 font-medium">Nudge</th>
						</tr>
					</thead>
					<tbody>
						{#each Array.from({ length: layerCount }, (_, i) => i + 1) as layerIdx}
							{@const channelId =
								Object.entries(layerByAssignment).find(
									([, value]) => value === layerIdx
								)?.[0] ?? String(layerIdx - 1)}
							<tr class="border-b border-border/70">
								<td class="px-3 py-2 text-text">Layer {layerIdx}</td>
								<td class="px-3 py-2">
									<select
										value={channelId}
										onchange={(event) => {
											const id = Number((event.currentTarget as HTMLSelectElement).value);
											const next = { ...layerByAssignment };
											for (const [key, value] of Object.entries(next)) {
												if (value === layerIdx) delete next[Number(key)];
											}
											next[id] = layerIdx;
											layerByAssignment = next;
										}}
										class="setup-control w-full px-2 py-1.5 text-text"
									>
										{#each pcaChoices() as choice}
											<option value={String(choice)}>{choice}</option>
										{/each}
									</select>
								</td>
								<td class="px-3 py-2">
									<label class="inline-flex items-center gap-2 text-text">
										<input
											class="setup-toggle"
											type="checkbox"
											checked={Boolean(invertByLayer[layerIdx])}
											onchange={(event) =>
												setInvertForLayer(
													layerIdx,
													(event.currentTarget as HTMLInputElement).checked
												)}
										/>
										<span>{invertByLayer[layerIdx] ? 'Yes' : 'No'}</span>
									</label>
								</td>
								<td class="px-3 py-2">
									<input
										type="number"
										min="0"
										max="180"
										placeholder={String(openAngle)}
										value={openAngleByLayer[layerIdx] ?? ''}
										oninput={(event) => {
											const val = (event.currentTarget as HTMLInputElement).value;
											openAngleByLayer = { ...openAngleByLayer, [layerIdx]: val };
										}}
										class="setup-control w-20 px-2 py-1.5 text-text"
									/>
								</td>
								<td class="px-3 py-2">
									<input
										type="number"
										min="0"
										max="180"
										placeholder={String(closedAngle)}
										value={closedAngleByLayer[layerIdx] ?? ''}
										oninput={(event) => {
											const val = (event.currentTarget as HTMLInputElement).value;
											closedAngleByLayer = { ...closedAngleByLayer, [layerIdx]: val };
										}}
										class="setup-control w-20 px-2 py-1.5 text-text"
									/>
								</td>
								<td class="px-3 py-2">
									<div class="flex items-center gap-1">
										<button
											onclick={() => void nudgeLayer(layerIdx, -nudgeDegrees)}
											class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg"
											title="Move left"
										>
											<ChevronLeft size={16} />
										</button>
										<input
											type="number"
											min="1"
											max="180"
											bind:value={nudgeDegrees}
											class="setup-control w-12 px-1 py-1 text-center text-xs text-text"
										/>
										<button
											onclick={() => void nudgeLayer(layerIdx, nudgeDegrees)}
											class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg"
											title="Move right"
										>
											<ChevronRight size={16} />
										</button>
										<button
											onclick={() => { selectedLayerIdx = selectedLayerIdx === layerIdx ? null : layerIdx; selectedServoId = null; }}
											class={`ml-1 px-2 py-1 text-[10px] font-medium transition-colors ${selectedLayerIdx === layerIdx ? 'border border-[#0055BF] bg-[#0055BF]/10 text-[#0055BF]' : 'border border-border bg-surface text-text-muted hover:bg-bg'}`}
											title="Select to use arrow keys"
										>
											{selectedLayerIdx === layerIdx ? '← → active' : 'keys'}
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<div class="flex flex-wrap items-center gap-3">
		<button
			onclick={saveServoSetup}
			disabled={saving}
			class="border border-[#00852B] bg-[#00852B] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#00852B]/90 disabled:cursor-not-allowed disabled:opacity-60"
		>
			{saving ? 'Saving…' : 'Save servo setup'}
		</button>
		{#if loading}
			<div class="text-sm text-text-muted">Loading current servo configuration…</div>
		{/if}
	</div>

	{#if servoIssues.length}
		<div
			class="border border-[#D01012] bg-[#FBE4E5] px-4 py-3 text-sm text-[#7A0A0B]"
		>
			{#each servoIssues as issue}
				<div>{issue.message}</div>
			{/each}
		</div>
	{/if}

	{#if errorMsg}
		<div
			class="border border-[#D01012] bg-[#FBE4E5] px-4 py-3 text-sm text-[#7A0A0B]"
		>
			{errorMsg}
		</div>
	{:else if statusMsg}
		<div
			class="border border-[#00852B] bg-[#D4EDDA] px-4 py-3 text-sm font-medium text-[#00852B]"
		>
			{statusMsg}
		</div>
	{/if}
	{/if}
</div>
