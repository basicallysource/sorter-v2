<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';
	import SerialPortPanel from './servo/SerialPortPanel.svelte';
	import ServoInventoryList from './servo/ServoInventoryList.svelte';
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

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

	type ServoSource = 'waveshare' | 'pca';

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
	let nudgeDegrees = $state<number>(5);

	// Effective number of assignable layers. If we have more servos on the bus
	// than the configured storage layers, expand so every servo can be mapped.
	const effectiveLayerCount = $derived(Math.max(layerCount, busServos.length));

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	// `accent` is the colored stripe down the servo's left edge: the one
	// deliberate side stripe in the app (the design system's docs/apps.md).
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
				tone: 'warning' as const,
				accent: 'border-l-warning',
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
				tone: undefined,
				accent: 'border-l-line-strong',
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
				tone: 'primary' as const,
				accent: 'border-l-primary',
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
			tone: 'success' as const,
			accent: 'border-l-success',
			title: 'Setup complete',
			description: `Calibrated and assigned to Layer ${layer}. Test the motion if you want a final check.`
		};
	}

	function applySettings(payload: any) {
		const storage = payload?.storage_layers ?? {};
		const servo = payload?.servo ?? {};
		const storageLayersRaw = Array.isArray(storage?.layers) ? storage.layers : [];
		const servoChannels = Array.isArray(servo?.channels) ? servo.channels : [];

		backend = servoSource === 'waveshare' ? 'waveshare' : 'pca9685';
		openAngle = Number(servo.open_angle ?? 10);
		closedAngle = Number(servo.closed_angle ?? 83);
		port = typeof servo.port === 'string' ? servo.port : '';
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
			if (selectedServoId === null) return;
			// Arrows in a field or a list (our Select is a button) are the field's, never a nudge.
			if (
				e.target instanceof HTMLElement &&
				e.target.closest('input, select, textarea, [aria-haspopup="listbox"], [role="listbox"]')
			)
				return;
			if (e.key === 'ArrowLeft') {
				e.preventDefault();
				void nudgeServo(selectedServoId, -nudgeDegrees);
			} else if (e.key === 'ArrowRight') {
				e.preventDefault();
				void nudgeServo(selectedServoId, nudgeDegrees);
			} else if (e.key === 'Escape') {
				selectedServoId = null;
			}
		}
		window.addEventListener('keydown', handleKeydown);

		return () => {
			clearInterval(interval);
			window.removeEventListener('keydown', handleKeydown);
		};
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if !settingsLoaded}
		{#if errorMsg}
			<Alert tone="danger" title="The servo configuration did not load">
				{errorMsg}
				{#snippet actions()}
					<Button size="sm" onclick={() => void loadSettings()}>Retry</Button>
				{/snippet}
			</Alert>
		{:else}
			<Panel>
				<p class="flex items-center gap-2 text-sm text-ink-muted">
					<Spinner size={16} />
					Loading the servo configuration…
				</p>
			</Panel>
		{/if}
	{:else}
		<Panel title="Servo backend">
			{#snippet actions()}
				{#if discoveredServoSource !== servoSource && onSourceChange}
					<Button size="sm" onclick={() => onSourceChange(discoveredServoSource)}>
						Use the detected one ({discoveredServoSource === 'waveshare' ? 'Waveshare' : 'PCA9685'})
					</Button>
				{/if}
			{/snippet}
			<p class="text-sm text-ink-muted">
				{#if servoSource !== 'waveshare'}
					No Waveshare servo bus found, so a PCA9685 on a control board is assumed.
				{:else if discoveredServoSource === 'waveshare'}
					The Waveshare SC serial bus was found{#if discoveredWaveshareServos > 0}, with
						<span class="text-ink">
							{discoveredWaveshareServos}
							{discoveredWaveshareServos === 1 ? 'servo' : 'servos'}
						</span> on it{/if}.
				{:else}
					Using the Waveshare SC serial bus.
				{/if}
			</p>
		</Panel>

		{#if servoSource === 'waveshare'}
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
			<ServoLayerCalibrator />
		{/if}

		{#if servoIssues.length}
			<Alert tone="danger">
				{#each servoIssues as issue}<p>{issue.message}</p>{/each}
			</Alert>
		{/if}
		{#if errorMsg}
			<Alert tone="danger">{errorMsg}</Alert>
		{:else if statusMsg}
			<Alert tone="success">{statusMsg}</Alert>
		{/if}
		<div class="flex flex-wrap items-center gap-3">
			<Button variant="primary" loading={saving} onclick={saveServoSetup}>Save the servos</Button>
			{#if loading}<span class="text-sm text-ink-muted">Loading the servo configuration…</span>{/if}
		</div>
	{/if}
</div>
