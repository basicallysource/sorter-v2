<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';

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
	type LayerDraft = {
		index: number;
		binCount: string;
		servoId: string;
		invert: boolean;
		liveOpen: boolean | null;
		telemetry: LayerTelemetry;
		testing: boolean;
		calibrating: boolean;
	};

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let allowedCounts = $state<number[]>([12, 18, 30]);
	let availableServoIds = $state<number[]>([]);
	let backend = $state<ServoBackend>('pca9685');
	let openAngle = $state(10);
	let closedAngle = $state(83);
	let port = $state('');
	let layers = $state<LayerDraft[]>([]);
	let liveFeedbackRequestInFlight = false;

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
		if (availableServoIds.length > 0) {
			return availableServoIds;
		}

		const ids = layers
			.map((layer) => Number(layer.servoId))
			.filter((value) => Number.isInteger(value) && value > 0);
		return [...new Set(ids)];
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

		const storageLayers = Array.isArray(storage?.layers) ? storage.layers : [];
		const servoChannels = Array.isArray(servo?.channels) ? servo.channels : [];
		layers = storageLayers.map((layer: any, index: number) => ({
			index: Number(layer?.index ?? index + 1),
			binCount: String(Number(layer?.bin_count ?? 12)),
			servoId: String(
				Number(
					servoChannels[index]?.id ?? (backend === 'waveshare' ? index + 1 : index)
				)
			),
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
			void loadLiveFeedback();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load storage layer settings';
		} finally {
			loading = false;
		}
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

	function parsedServoChannels(): Array<{ id: number; invert: boolean }> {
		const seenIds = new Set<number>();
		const validPcaChannels = new Set(pcaChannelChoices());

		return layers.map((layer) => {
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
			const channels = parsedServoChannels();

			const storageRes = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/storage-layers`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layer_bin_counts: layerBinCounts })
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

			applySettings({
				storage_layers: storagePayload?.settings ?? storagePayload?.storage_layers,
				servo: servoPayload?.settings
			});
			void loadLiveFeedback();

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

	function updateLayerCount(index: number, value: string) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, binCount: value } : layer
		);
	}

	function updateLayerServoId(index: number, value: string) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, servoId: value } : layer
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

	$effect(() => {
		loadedMachineKey;
		backend;
		void loadLiveFeedback();
	});

	onMount(() => {
		const interval = setInterval(() => {
			void loadLiveFeedback();
		}, 500);
		return () => clearInterval(interval);
	});
</script>

<div class="flex flex-col gap-4">
	<div class="flex flex-wrap items-end gap-3">
		<label class="dark:text-text-dark text-xs text-text">
			Backend
			<select
				bind:value={backend}
				disabled={loading || saving}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 block w-40 border border-border bg-bg px-2 py-1.5 text-sm text-text"
			>
				<option value="pca9685">PCA9685</option>
				<option value="waveshare">Waveshare SC</option>
			</select>
		</label>

		{#if backend === 'pca9685'}
			<label class="dark:text-text-dark text-xs text-text">
				Open Angle
				<input
					type="number"
					min="0"
					max="180"
					step="1"
					bind:value={openAngle}
					disabled={loading || saving}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 block w-24 border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
			<label class="dark:text-text-dark text-xs text-text">
				Closed Angle
				<input
					type="number"
					min="0"
					max="180"
					step="1"
					bind:value={closedAngle}
					disabled={loading || saving}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 block w-24 border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		{:else}
			<label class="dark:text-text-dark min-w-0 flex-1 text-xs text-text">
				Port
				<input
					type="text"
					bind:value={port}
					placeholder="Auto-detect"
					disabled={loading || saving}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		{/if}

		<div class="flex items-center gap-2 pb-0.5">
			<button
				onclick={saveSettings}
				disabled={loading || saving || layers.length === 0}
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				{saving ? 'Saving...' : 'Save'}
			</button>
			<button
				onclick={loadSettings}
				disabled={loading || saving}
				class="dark:text-text-muted-dark cursor-pointer text-xs text-text-muted hover:text-text disabled:cursor-not-allowed disabled:opacity-50 dark:hover:text-text-dark"
			>
				{loading ? 'Loading...' : 'Reload'}
			</button>
		</div>
	</div>

	{#if errorMsg}
		<div class="text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
	{/if}

	{#if layers.length === 0 && !loading}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">
			No storage layers found.
		</div>
	{:else}
		<div class="dark:border-border-dark overflow-hidden border border-border">
			<table class="w-full text-sm">
				<thead>
					<tr class="dark:border-border-dark dark:bg-surface-dark border-b border-border bg-surface text-left text-xs">
						<th class="dark:text-text-muted-dark px-3 py-2 font-medium text-text-muted">Layer</th>
						<th class="dark:text-text-muted-dark px-3 py-2 font-medium text-text-muted">Bins</th>
						<th class="dark:text-text-muted-dark px-3 py-2 font-medium text-text-muted">{backend === 'waveshare' ? 'Servo ID' : 'Channel'}</th>
						<th class="dark:text-text-muted-dark px-3 py-2 font-medium text-text-muted">Invert</th>
						{#if backend === 'waveshare'}
							<th class="dark:text-text-muted-dark px-3 py-2 font-medium text-text-muted">Position</th>
						{/if}
						<th class="dark:text-text-muted-dark px-3 py-2 font-medium text-text-muted">State</th>
						<th class="dark:text-text-muted-dark px-3 py-2 text-right font-medium text-text-muted">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each layers as layer, index}
						<tr class="dark:border-border-dark dark:bg-bg-dark border-b border-border bg-bg last:border-b-0">
							<td class="dark:text-text-dark px-3 py-2 font-medium text-text">{layer.index}</td>
							<td class="px-3 py-2">
								<select
									value={layer.binCount}
									onchange={(event) => updateLayerCount(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
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
										class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
									>
										{#each waveshareServoChoices() as servoId}
											<option value={String(servoId)}>{servoId}</option>
										{/each}
									</select>
								{:else}
									<select
										value={layer.servoId}
										onchange={(event) => updateLayerServoId(index, event.currentTarget.value)}
										disabled={loading || saving}
										class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
									>
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
									disabled={loading || saving}
								/>
							</td>
							{#if backend === 'waveshare'}
								<td class="dark:text-text-muted-dark px-3 py-2 font-mono text-xs text-text-muted">
									{formatTelemetryValue(layer.telemetry.position)}
									<span class="dark:text-text-muted-dark/50 text-text-muted/50">/ {formatTelemetryValue(layer.telemetry.openPosition)} · {formatTelemetryValue(layer.telemetry.closedPosition)}</span>
									{#if layer.telemetry.error}
										<span class="ml-1 text-red-500" title={layer.telemetry.error}>!</span>
									{/if}
								</td>
							{/if}
							<td class="px-3 py-2">
								{#if layer.liveOpen !== null}
									<span class="inline-flex items-center gap-1 text-xs {layer.liveOpen ? 'text-green-600 dark:text-green-400' : 'dark:text-text-muted-dark text-text-muted'}">
										<span class="h-1.5 w-1.5 rounded-full {layer.liveOpen ? 'bg-green-500' : 'dark:bg-border-dark bg-border'}"></span>
										{layer.liveOpen ? 'Open' : 'Closed'}
									</span>
								{:else}
									<span class="dark:text-text-muted-dark text-xs text-text-muted">--</span>
								{/if}
							</td>
							<td class="px-3 py-2 text-right">
								<div class="flex items-center justify-end gap-1.5">
									<button
										onclick={() => toggleLayerServo(index)}
										disabled={loading || saving || layer.testing}
										class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
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
											disabled={loading || saving || layer.calibrating}
											class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-2 py-1 text-xs text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
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
</div>
