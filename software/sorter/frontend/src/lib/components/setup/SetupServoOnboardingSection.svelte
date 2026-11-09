<!--
	The door servos of a machine whose control board has no servo bus of its
	own: PWM servos on a board (the layer calibrator), or serial servos on a
	USB adapter (scan, give each its own ID, calibrate, assign it a layer).
	Which of the two is what was saved, until the person picks the other; it is
	never guessed again after the motors power up. A servo's ID changes only
	when the person presses the button for it.
-->
<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { errorMessage, getJson, postJson } from '$lib/api/http';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount, untrack } from 'svelte';
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
		initialSource = 'pca',
		adapterServos = null,
		onSaved = null
	}: {
		// The kind saved for this machine.
		initialSource?: ServoSource;
		// Servos a USB adapter answered with, when the buses were probed.
		adapterServos?: number | null;
		onSaved?: (() => void | Promise<void>) | null;
	} = $props();

	let servoSource = $state<ServoSource>(untrack(() => initialSource));
	// Bumped after a save, so the PWM calibrator loads what was saved.
	let calibratorKey = $state(0);

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
	let storageLayers = $state<
		Array<{ bin_count: number; enabled: boolean; max_pieces_per_bin: number | null; max_dimension_mm: number | null }>
	>([]);
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

	let selectedServoId = $state<number | null>(null);
	let nudgeDegrees = $state<number>(5);

	// A servo is assigned to one of the layers the Bins step set; a servo past
	// their count waits for a layer.
	const effectiveLayerCount = $derived(layerCount);
	const extraServos = $derived(Math.max(0, busServos.length - layerCount));

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
			max_pieces_per_bin: typeof sl?.max_pieces_per_bin === 'number' ? sl.max_pieces_per_bin : null,
			max_dimension_mm: typeof sl?.max_dimension_mm === 'number' ? sl.max_dimension_mm : null
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
			applySettings(await getJson(currentBackendBaseUrl(), '/api/hardware-config'));
			settingsLoaded = true;
			if (backend === 'waveshare') {
				void loadWaveshareInventory({ refresh: false, silent: true });
			}
		} catch (e) {
			errorMsg = errorMessage(e, 'The servo setup did not load.');
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
		busServos = Array.isArray(payload?.servos) ? payload.servos : [];
		suggestedNextId =
			typeof payload?.suggested_next_id === 'number' ? payload.suggested_next_id : null;
		highestSeenId = typeof payload?.highest_seen_id === 'number' ? payload.highest_seen_id : 0;
		if (!port.trim() && typeof payload?.current_port === 'string' && payload.current_port) {
			port = payload.current_port;
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
			const path = `/api/hardware-config/waveshare/${refresh ? 'rescan' : 'status'}`;
			const query = { port: port.trim() || null };
			applyWaveshareInventory(
				refresh
					? await postJson(currentBackendBaseUrl(), path, undefined, { query })
					: await getJson(currentBackendBaseUrl(), path, { query })
			);
		} catch (e) {
			if (!options.silent) {
				errorMsg = errorMessage(e, 'The servo adapter was not scanned.');
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
			const payload = await postJson<{ message?: string }>(
				currentBackendBaseUrl(),
				`/api/hardware-config/waveshare/servos/${servoId}/calibrate`
			);
			statusMsg = payload?.message ?? `Servo ${servoId} calibrated.`;
			await loadWaveshareInventory({ refresh: true });
		} catch (e) {
			errorMsg = errorMessage(e, `Servo ${servoId} was not calibrated.`);
		} finally {
			setBusy(servoId, null);
		}
	}

	async function moveServo(servoId: number, position: 'open' | 'close' | 'center') {
		setBusy(servoId, 'moving');
		errorMsg = null;
		statusMsg = '';
		try {
			await postJson(currentBackendBaseUrl(), `/api/hardware-config/waveshare/servos/${servoId}/move`, {
				position
			});
			lastMoveByServoId = { ...lastMoveByServoId, [servoId]: position };
		} catch (e) {
			errorMsg = errorMessage(e, `Servo ${servoId} did not move.`);
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
			const data = await postJson<{ raw_position?: number; limits?: unknown }>(
				currentBackendBaseUrl(),
				`/api/hardware-config/waveshare/servos/${servoId}/nudge`,
				{ degrees }
			);
			const raw = data.raw_position;
			if (typeof raw === 'number' && data.limits) {
				busServos = busServos.map((s) => (s.id === servoId ? { ...s, position: raw } : s));
			}
		} catch (e) {
			errorMsg = errorMessage(e, `Servo ${servoId} did not move.`);
		} finally {
			setBusy(servoId, null);
		}
	}

	async function promoteServoId(currentId: number, newId: number) {
		setBusy(currentId, 'promoting');
		errorMsg = null;
		statusMsg = '';
		try {
			const payload = await postJson<{ message?: string }>(
				currentBackendBaseUrl(),
				`/api/hardware-config/waveshare/servos/${currentId}/set-id`,
				{ new_id: newId }
			);
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
		} catch (e) {
			errorMsg = errorMessage(e, 'The servo ID was not changed.');
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
		// One channel per layer, as many as the layers saved: the machine
		// refuses any other count.
		for (let layer = 1; layer <= layerCount; layer++) {
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
			await postJson(currentBackendBaseUrl(), '/api/hardware-config/storage-layers', {
				layers: storageLayers
			});
			const payload = await postJson<{ message?: string }>(
				currentBackendBaseUrl(),
				'/api/hardware-config/servo',
				{
					backend,
					open_angle: openAngle,
					closed_angle: closedAngle,
					port: backend === 'waveshare' ? port.trim() || null : null,
					channels
				}
			);
			statusMsg = payload?.message ?? 'Servo setup saved.';
			calibratorKey += 1;
			await loadSettings();
			if (onSaved) {
				await onSaved();
			}
		} catch (e) {
			errorMsg = errorMessage(e, 'The servos were not saved.');
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
		<Panel
			title="How the doors are turned"
			description="PWM servos wired to a control board, or serial servos on a USB servo adapter."
		>
			<SegmentedControl
				label="How the doors are turned"
				bind:value={servoSource}
				options={[
					{ value: 'pca', label: 'PWM servos on a board' },
					{ value: 'waveshare', label: 'USB servo adapter' }
				]}
			/>
			{#if servoSource !== initialSource}
				<p class="mt-3 text-sm text-ink-muted">Saved when you save the servos below.</p>
			{:else if servoSource === 'pca' && adapterServos}
				<p class="mt-3 text-sm text-ink-muted">
					A USB servo adapter answered with {adapterServos}
					{adapterServos === 1 ? 'servo' : 'servos'} on it. Choose it above if the doors are on it.
				</p>
			{/if}
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
			{#key calibratorKey}<ServoLayerCalibrator />{/key}
		{/if}
		{#if servoSource === 'waveshare' && extraServos > 0}
			<Alert tone="warning">
				There {extraServos === 1 ? 'is a servo' : `are ${extraServos} servos`} on the bus past the
				{layerCount} layers. Add layers in the Bins step to give {extraServos === 1 ? 'it' : 'them'} a door.
			</Alert>
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
		{#if servoSource === 'waveshare' || servoSource !== initialSource}
			<div class="flex flex-wrap items-center gap-3">
				<Button variant="primary" loading={saving} onclick={saveServoSetup}>Save the servos</Button>
				{#if loading}<span class="text-sm text-ink-muted">Loading the servo configuration…</span>{/if}
			</div>
		{/if}
	{/if}
</div>
