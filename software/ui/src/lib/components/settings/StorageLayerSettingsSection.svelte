<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type ServoBackend = 'pca9685' | 'waveshare';
	type LayerDraft = {
		index: number;
		binCount: string;
		servoId: string;
		invert: boolean;
		liveOpen: boolean | null;
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
	let availablePcaChannels = $state<number[]>([]);
	let backend = $state<ServoBackend>('pca9685');
	let openAngle = $state(10);
	let closedAngle = $state(83);
	let port = $state('');
	let layers = $state<LayerDraft[]>([]);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function pcaChannelChoices(): number[] {
		return availablePcaChannels.length > 0
			? availablePcaChannels
			: Array.from({ length: layers.length }, (_, index) => index);
	}

	function applySettings(payload: any) {
		const storage = payload?.storage_layers ?? payload?.settings ?? {};
		const servo = payload?.servo ?? {};
		const previousStates = new Map(
			layers.map((layer) => [layer.index, { liveOpen: layer.liveOpen }])
		);

		allowedCounts = Array.isArray(storage?.allowed_bin_counts)
			? storage.allowed_bin_counts.filter((value: unknown): value is number => typeof value === 'number')
			: [12, 18, 30];

		backend = servo.backend === 'waveshare' ? 'waveshare' : 'pca9685';
		openAngle = Number(servo.open_angle ?? 10);
		closedAngle = Number(servo.closed_angle ?? 83);
		port = typeof servo.port === 'string' ? servo.port : '';
		availablePcaChannels = Array.isArray(servo.available_channel_ids)
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
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load storage layer settings';
		} finally {
			loading = false;
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

	function updateLayerInvert(index: number, value: boolean) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, invert: value } : layer
		);
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});
</script>

<div class="flex flex-col gap-4">
	<div class="dark:text-text-muted-dark text-sm text-text-muted">
		Configure each storage layer as one row: bin count, servo assignment, invert, and quick test
		controls. Layer-count changes update the bin-layout file and require a backend restart to fully
		apply; servo angle or invert changes can apply live when the backend wiring stays the same.
	</div>

	<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
		<label class="dark:text-text-dark text-xs text-text">
			Servo Backend
			<select
				bind:value={backend}
				disabled={loading || saving}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
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
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
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
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		{:else}
			<label class="dark:text-text-dark text-xs text-text md:col-span-2 xl:col-span-3">
				Servo Bus Port
				<input
					type="text"
					bind:value={port}
					placeholder="Auto-detect if left blank"
					disabled={loading || saving}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		{/if}
	</div>

	{#if layers.length === 0 && !loading}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">
			No storage layers were found in the current layout file.
		</div>
	{:else}
		<div class="flex flex-col gap-2">
			{#each layers as layer, index}
				<div class="dark:border-border-dark dark:bg-bg-dark border border-border bg-bg px-3 py-3">
					<div class="grid grid-cols-1 gap-3 xl:grid-cols-[140px_140px_160px_120px_minmax(0,1fr)] xl:items-end">
						<div class="dark:text-text-dark flex items-center text-sm font-medium text-text">
							Layer {layer.index}
						</div>

						<label class="dark:text-text-dark text-xs text-text">
							Bins
							<select
								value={layer.binCount}
								onchange={(event) => updateLayerCount(index, event.currentTarget.value)}
								disabled={loading || saving}
								class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark mt-1 w-full border border-border bg-surface px-2 py-1.5 text-sm text-text"
							>
								{#each allowedCounts as count}
									<option value={String(count)}>{count}</option>
								{/each}
							</select>
						</label>

						<label class="dark:text-text-dark text-xs text-text">
							{backend === 'waveshare' ? 'Servo ID' : 'Servo Channel'}
							{#if backend === 'waveshare'}
								<input
									type="number"
									min="1"
									max="253"
									step="1"
									value={layer.servoId}
									oninput={(event) => updateLayerServoId(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark mt-1 w-full border border-border bg-surface px-2 py-1.5 text-sm text-text"
								/>
							{:else}
								<select
									value={layer.servoId}
									onchange={(event) => updateLayerServoId(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark mt-1 w-full border border-border bg-surface px-2 py-1.5 text-sm text-text"
								>
									{#each pcaChannelChoices() as channel}
										<option value={String(channel)}>{channel}</option>
									{/each}
								</select>
							{/if}
						</label>

						<label class="dark:text-text-dark flex items-center gap-2 text-xs text-text xl:pb-2">
							<input
								type="checkbox"
								checked={layer.invert}
								onchange={(event) => updateLayerInvert(index, event.currentTarget.checked)}
								disabled={loading || saving}
							/>
							Invert
						</label>

						<div class="flex flex-wrap items-center gap-2">
							<button
								onclick={() => toggleLayerServo(index)}
								disabled={loading || saving || layer.testing}
								class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
							>
								{#if layer.testing}
									Testing...
								{:else if layer.liveOpen === true}
									Close Test
								{:else if layer.liveOpen === false}
									Open Test
								{:else}
									Open / Close Test
								{/if}
							</button>

							{#if backend === 'waveshare'}
								<button
									onclick={() => calibrateLayerServo(index)}
									disabled={loading || saving || layer.calibrating}
									class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
								>
									{layer.calibrating ? 'Calibrating...' : 'Calibrate'}
								</button>
							{/if}

							{#if layer.liveOpen !== null}
								<div class="dark:text-text-muted-dark text-xs text-text-muted">
									{layer.liveOpen ? 'Currently open' : 'Currently closed'}
								</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<div class="flex flex-wrap items-center gap-2">
		<button
			onclick={saveSettings}
			disabled={loading || saving || layers.length === 0}
			class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{saving ? 'Saving...' : 'Save Storage Layer Settings'}
		</button>
		<button
			onclick={loadSettings}
			disabled={loading || saving}
			class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
		>
			{loading ? 'Loading...' : 'Reload'}
		</button>
	</div>

	{#if errorMsg}
		<div class="text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
