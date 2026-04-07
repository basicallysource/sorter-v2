<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';

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
	// servoId → layer index (1-based). For PCA, channelId → layer index.
	let layerByAssignment = $state<Record<number, number>>({});
	// per-layer invert (1-based layer index → invert)
	let invertByLayer = $state<Record<number, boolean>>({});

	// per-servo UI state
	let busyByServoId = $state<Record<number, string>>({}); // 'calibrating' | 'moving' | 'promoting'
	let lastMoveByServoId = $state<Record<number, 'open' | 'close' | 'center'>>({});
	// Track servo ids we've already auto-promoted this session so we don't loop.
	let autoPromotedIds = $state<Set<number>>(new Set());

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

	function applySettings(payload: any) {
		const storage = payload?.storage_layers ?? {};
		const servo = payload?.servo ?? {};
		const storageLayers = Array.isArray(storage?.layers) ? storage.layers : [];
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

		layerCount = Math.max(storageLayers.length, Number(servo.layer_count ?? 0));

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

	async function saveServoSetup() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const channels = buildChannelsForSave();
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
		return () => clearInterval(interval);
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
						{@const calibrated =
							typeof servo.min_limit === 'number' &&
							typeof servo.max_limit === 'number' &&
							(servo.max_limit ?? 0) - (servo.min_limit ?? 0) >= 20}
						{@const layer = layerByAssignment[servo.id] ?? 0}
						{@const lastMove = lastMoveByServoId[servo.id]}
						{@const inverted = layer > 0 ? Boolean(invertByLayer[layer]) : false}
						{@const isFactory = servo.id === 1 && suggestedNextId !== null}
						{@const accent = isFactory
							? 'border-l-[#F2A900]'
							: layer > 0
								? 'border-l-[#00852B]'
								: calibrated
									? 'border-l-[#0055BF]'
									: 'border-l-[#C9C7C0]'}
						<div class="border border-border border-l-4 bg-surface {accent}">
							<!-- Identity row: ID badge · model/range/voltage · layer dropdown -->
							<div class="flex flex-wrap items-center gap-4 px-4 py-3">
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
									<div class="mt-1 flex flex-wrap items-center gap-2 text-xs">
										{#if calibrated}
											<span
												class="inline-flex items-center gap-1 border border-[#0055BF]/30 bg-[#0055BF]/10 px-2 py-0.5 font-medium text-[#0055BF]"
											>
												<span class="h-1.5 w-1.5 rounded-full bg-[#0055BF]"></span>
												Calibrated · {servo.min_limit}–{servo.max_limit}
											</span>
										{:else}
											<span
												class="inline-flex items-center gap-1 border border-border bg-bg px-2 py-0.5 font-medium text-text-muted"
											>
												<span class="h-1.5 w-1.5 rounded-full bg-text-muted"></span>
												Not calibrated
											</span>
										{/if}
										{#if layer > 0}
											<span
												class="inline-flex items-center gap-1 border border-[#00852B]/30 bg-[#00852B]/10 px-2 py-0.5 font-medium text-[#00852B]"
											>
												<span class="h-1.5 w-1.5 rounded-full bg-[#00852B]"></span>
												Layer {layer}{inverted ? ' · swapped' : ''}
											</span>
										{/if}
									</div>
								</div>

								<div class="flex flex-col items-end gap-1">
									<span class="text-[10px] uppercase tracking-wider text-text-muted">Assigned to</span>
									<select
										value={String(layer)}
										onchange={(event) =>
											assignLayer(
												servo.id,
												Number((event.currentTarget as HTMLSelectElement).value)
											)}
										class="setup-control px-3 py-1.5 text-sm font-medium text-text"
									>
										<option value="0">— Unassigned —</option>
										{#each unassignedLayers(layer) as layerOption}
											<option value={String(layerOption)}>Layer {layerOption}</option>
										{/each}
									</select>
								</div>
							</div>

							{#if isFactory}
								<div
									class="flex flex-wrap items-center justify-between gap-3 border-t border-[#F2A900]/40 bg-[#FFF7E0] px-4 py-2 text-xs text-[#7A5A00]"
								>
									<span>
										Brand-new servo on factory ID <span class="font-semibold">1</span>.
										Promote it before the next servo joins the bus.
									</span>
									<button
										onclick={() => promoteServoId(servo.id, suggestedNextId!)}
										disabled={!!busy}
										class="border border-[#F2A900] bg-[#F2A900] px-3 py-1.5 text-xs font-semibold text-[#3D2A00] transition-colors hover:bg-[#F2A900]/90 disabled:cursor-not-allowed disabled:opacity-60"
									>
										{busy === 'promoting' ? 'Promoting…' : `Promote to ID ${suggestedNextId}`}
									</button>
								</div>
							{/if}

							<!-- Action toolbar -->
							<div
								class="flex flex-wrap items-center gap-2 border-t border-border bg-bg/40 px-4 py-2"
							>
								<button
									onclick={() => calibrateServo(servo.id)}
									disabled={!!busy}
									class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
								>
									{busy === 'calibrating'
										? 'Calibrating…'
										: calibrated
											? 'Recalibrate'
											: 'Auto-calibrate'}
								</button>
								<span class="h-4 w-px bg-border"></span>
								<button
									onclick={() => toggleOpenClose(servo.id)}
									disabled={!!busy || !calibrated}
									class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
								>
									{busy === 'moving'
										? 'Moving…'
										: lastMove === 'open'
											? 'Move to closed'
											: 'Move to open'}
								</button>
								<button
									onclick={() => toggleInvertForLayer(layer)}
									disabled={!calibrated || layer === 0}
									title={layer === 0
										? 'Assign a layer first to remember this swap'
										: 'Use this if the servo opens when it should close'}
									class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
								>
									{inverted ? '↺ Open/close swapped' : 'Swap open/close'}
								</button>
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
			<div class="text-sm font-semibold text-text">Open/close angles</div>
			<div class="mt-1 text-xs text-text-muted">
				PCA9685 servos can't store calibrated limits on the device, so the same open/close
				angles apply to every channel. Use the layer's <span class="font-medium text-text">Invert</span>
				toggle below if a specific layer is mounted upside-down.
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
