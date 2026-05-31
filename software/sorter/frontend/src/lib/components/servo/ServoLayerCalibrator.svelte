<script lang="ts">
	import {
		ChevronLeft,
		ChevronRight,
		Lock,
		LockOpen,
		DoorOpen,
		DoorClosed,
		Crosshair,
		Save,
		RotateCcw,
		Plus,
		Trash2,
		Keyboard,
		Cog
	} from 'lucide-svelte';
	import ServoSpeedSettings from './ServoSpeedSettings.svelte';
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { Alert, Button } from '$lib/components/primitives';

	type ServoBackend = 'pca9685' | 'waveshare';

	type LayerDraft = {
		layerIndex: number; // 0-based, matches backend layer/servo index
		label: string;
		enabled: boolean;
		channel: string; // PCA channel id as string ('' = unassigned)
		invert: boolean;
		binCount: string;
		maxPiecesPerBin: string;
		openAngle: number | null;
		closedAngle: number | null;
		currentAngle: number | null;
		busy: boolean;
		lockStatus: 'idle' | 'saving' | 'saved' | 'error';
		lockError: string;
	};

	let {
		showDirections = false
	}: {
		showDirections?: boolean;
	} = $props();

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let backend = $state<ServoBackend>('pca9685');
	let layers = $state<LayerDraft[]>([]);
	let channelChoices = $state<number[]>([]);
	let allowedCounts = $state<number[]>([6, 12, 18, 30]);
	let jogStep = $state(5);
	let selectedIndex = $state<number | null>(null);

	// Signature of everything the "Save servo layers" button persists (layer
	// add/remove, channel, invert, bin count, max/bin, active). Captured at load
	// and after each save; `dirty` flags the form whenever the two diverge. Open/
	// closed angles and speeds persist through their own endpoints, so they're
	// deliberately left out — they don't dirty this form.
	let savedSignature = $state('');
	function layerSignature(list: LayerDraft[]): string {
		return JSON.stringify(
			list.map((l) => [l.enabled, l.channel, l.invert, l.binCount, l.maxPiecesPerBin.trim()])
		);
	}
	let dirty = $derived(layerSignature(layers) !== savedSignature);

	// Global servo speeds (°/s). null = not overridden (firmware default applies).
	let openSpeed = $state<number | null>(null);
	let closeSpeed = $state<number | null>(null);
	let homingSpeed = $state<number | null>(null);

	// Global angles are no longer used to drive PCA servos, but the /servo
	// endpoint still round-trips them, so preserve whatever is stored.
	let globalOpenAngle: number | null = null;
	let globalClosedAngle: number | null = null;
	let port: string | null = null;

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function layerIsCalibrated(layer: LayerDraft): boolean {
		return layer.openAngle !== null && layer.closedAngle !== null;
	}

	function layerHasChannel(layer: LayerDraft): boolean {
		return layer.channel.trim().length > 0;
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			const servo = payload?.servo ?? {};
			backend = servo.backend === 'waveshare' ? 'waveshare' : 'pca9685';
			globalOpenAngle = typeof servo.open_angle === 'number' ? servo.open_angle : null;
			globalClosedAngle = typeof servo.closed_angle === 'number' ? servo.closed_angle : null;
			openSpeed = typeof servo.open_speed === 'number' ? servo.open_speed : null;
			closeSpeed = typeof servo.close_speed === 'number' ? servo.close_speed : null;
			homingSpeed = typeof servo.homing_speed === 'number' ? servo.homing_speed : null;
			port = typeof servo.port === 'string' ? servo.port : null;
			channelChoices = Array.isArray(servo.available_channel_ids)
				? servo.available_channel_ids
						.map((value: any) => Number(value))
						.filter((value: number) => Number.isInteger(value))
				: [];

			const storage = payload?.storage_layers ?? {};
			allowedCounts = Array.isArray(storage.allowed_bin_counts)
				? storage.allowed_bin_counts.filter((v: unknown): v is number => typeof v === 'number')
				: [6, 12, 18, 30];

			const servoChannels: Array<{ id: number | null; invert: boolean }> = Array.isArray(
				servo.channels
			)
				? servo.channels
				: [];
			const storageLayers: any[] = Array.isArray(storage.layers) ? storage.layers : [];

			const count = Math.max(servoChannels.length, storageLayers.length, Number(servo.layer_count ?? 0));
			const next: LayerDraft[] = [];
			for (let i = 0; i < count; i++) {
				const channel = servoChannels[i];
				const sl = storageLayers[i] ?? {};
				next.push({
					layerIndex: i,
					label: `Layer ${i + 1}`,
					enabled: Boolean(sl.enabled ?? true),
					channel: channel && typeof channel.id === 'number' ? String(channel.id) : '',
					invert: Boolean(channel?.invert),
					binCount: String(Number(sl.bin_count ?? 12)),
					maxPiecesPerBin:
						typeof sl.max_pieces_per_bin === 'number' && sl.max_pieces_per_bin > 0
							? String(sl.max_pieces_per_bin)
							: '',
					openAngle: typeof sl.servo_open_angle === 'number' ? sl.servo_open_angle : null,
					closedAngle: typeof sl.servo_closed_angle === 'number' ? sl.servo_closed_angle : null,
					currentAngle:
						typeof sl.servo_current_angle === 'number' ? sl.servo_current_angle : null,
					busy: false,
					lockStatus: 'idle',
					lockError: ''
				});
			}
			layers = next;
			savedSignature = layerSignature(next);
			if (selectedIndex !== null && selectedIndex >= layers.length) selectedIndex = null;
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load servo layers';
		} finally {
			loading = false;
		}
	}

	function setLayer(layerIndex: number, patch: Partial<LayerDraft>) {
		layers = layers.map((layer) =>
			layer.layerIndex === layerIndex ? { ...layer, ...patch } : layer
		);
	}

	async function postLayerAction(
		layerIndex: number,
		path: string,
		body: unknown
	): Promise<any | null> {
		errorMsg = null;
		statusMsg = '';
		setLayer(layerIndex, { busy: true });
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/servo/layers/${layerIndex}/${path}`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(body)
				}
			);
			if (!res.ok) throw new Error(await res.text());
			return await res.json();
		} catch (e: any) {
			errorMsg = e.message ?? `Failed to ${path} layer ${layerIndex + 1}`;
			return null;
		} finally {
			setLayer(layerIndex, { busy: false });
		}
	}

	async function jog(layerIndex: number, degrees: number) {
		const result = await postLayerAction(layerIndex, 'nudge', { degrees });
		if (result && typeof result.new_angle === 'number') {
			setLayer(layerIndex, { currentAngle: result.new_angle });
		}
	}

	async function lockAngle(layerIndex: number, which: 'open' | 'closed') {
		// The /lock endpoint persists the angle to the backend immediately, so
		// locking is the save — the per-layer indicator reflects that write.
		setLayer(layerIndex, { lockStatus: 'saving', lockError: '' });
		const result = await postLayerAction(layerIndex, 'lock', { which });
		if (result) {
			setLayer(layerIndex, {
				openAngle: typeof result.open_angle === 'number' ? result.open_angle : null,
				closedAngle: typeof result.closed_angle === 'number' ? result.closed_angle : null,
				lockStatus: 'saved',
				lockError: ''
			});
			statusMsg = result.message ?? `Layer ${layerIndex + 1} ${which} angle locked.`;
		} else {
			setLayer(layerIndex, { lockStatus: 'error', lockError: errorMsg ?? 'Save failed' });
		}
	}

	async function moveTo(layerIndex: number, angle: number | null) {
		if (angle === null) return;
		const result = await postLayerAction(layerIndex, 'move-to', { angle });
		if (result && typeof result.new_angle === 'number') {
			setLayer(layerIndex, { currentAngle: result.new_angle });
		}
	}

	function toggleSelect(layerIndex: number) {
		selectedIndex = selectedIndex === layerIndex ? null : layerIndex;
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const channels = layers.map((layer, index) => {
				const id = layer.channel.trim().length > 0 ? Number(layer.channel) : null;
				if (id !== null && (!Number.isInteger(id) || id < 0)) {
					throw new Error(`Layer ${index + 1} has an invalid channel.`);
				}
				if (id === null && layer.enabled) {
					throw new Error(`Layer ${index + 1} needs a channel while it is active.`);
				}
				return { id, invert: layer.invert };
			});

			const storageLayers = layers.map((layer) => {
				const trimmed = layer.maxPiecesPerBin.trim();
				let maxPieces: number | null = null;
				if (trimmed.length > 0) {
					const parsed = Number(trimmed);
					if (!Number.isInteger(parsed) || parsed <= 0) {
						throw new Error(`${layer.label} max pieces per bin must be a positive integer.`);
					}
					maxPieces = parsed;
				}
				return {
					bin_count: Number(layer.binCount),
					enabled: layer.enabled,
					servo_open_angle: layer.openAngle,
					servo_closed_angle: layer.closedAngle,
					max_pieces_per_bin: maxPieces
				};
			});

			const storageRes = await fetch(
				`${currentBackendBaseUrl()}/api/hardware-config/storage-layers`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ layers: storageLayers })
				}
			);
			if (!storageRes.ok) throw new Error(await storageRes.text());

			const servoRes = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/servo`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					backend: 'pca9685',
					open_angle: globalOpenAngle,
					closed_angle: globalClosedAngle,
					open_speed: openSpeed,
					close_speed: closeSpeed,
					homing_speed: homingSpeed,
					port,
					channels
				})
			});
			if (!servoRes.ok) throw new Error(await servoRes.text());

			statusMsg = 'Servo layer settings saved.';
			await loadSettings();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save servo layer settings';
		} finally {
			saving = false;
		}
	}

	function nextChannel(): string {
		// Auto-assign the next channel after the highest one already used, so a
		// fresh layer lands on an unused channel without manual picking. Falls back
		// to the first available choice (or blank) when nothing is assigned yet.
		const used = layers
			.map((l) => (l.channel.trim().length > 0 ? Number(l.channel) : null))
			.filter((n): n is number => n !== null && Number.isInteger(n));
		if (used.length > 0) {
			const candidate = Math.max(...used) + 1;
			if (channelChoices.length === 0 || channelChoices.includes(candidate)) {
				return String(candidate);
			}
		}
		const firstFree = channelChoices.find((c) => !used.includes(c));
		return firstFree !== undefined ? String(firstFree) : '';
	}

	function addLayer() {
		const nextIndex = layers.length;
		layers = [
			...layers,
			{
				layerIndex: nextIndex,
				label: `Layer ${nextIndex + 1}`,
				enabled: true,
				channel: nextChannel(),
				invert: false,
				binCount: String(allowedCounts[0] ?? 12),
				maxPiecesPerBin: '',
				openAngle: null,
				closedAngle: null,
				currentAngle: null,
				busy: false,
				lockStatus: 'idle',
				lockError: ''
			}
		];
	}

	function removeLayer(layerIndex: number) {
		layers = layers
			.filter((l) => l.layerIndex !== layerIndex)
			.map((l, i) => ({ ...l, layerIndex: i, label: `Layer ${i + 1}` }));
		if (selectedIndex === layerIndex) selectedIndex = null;
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ??
			'__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});

	onMount(() => {
		function handleKeydown(event: KeyboardEvent) {
			if (selectedIndex === null) return;
			if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement)
				return;
			if (event.key === 'ArrowLeft') {
				event.preventDefault();
				void jog(selectedIndex, -jogStep);
			} else if (event.key === 'ArrowRight') {
				event.preventDefault();
				void jog(selectedIndex, jogStep);
			} else if (event.key === 'Escape') {
				selectedIndex = null;
			}
		}
		window.addEventListener('keydown', handleKeydown);
		return () => window.removeEventListener('keydown', handleKeydown);
	});
</script>

<div class="flex flex-col gap-4">
	{#if showDirections}
		<Alert variant="info">
			<div class="flex flex-col gap-1 text-sm">
				<div class="font-semibold">Calibrate each door servo before sorting</div>
				<ol class="ml-4 list-decimal space-y-0.5">
					<li>Pick the channel this layer's servo is wired to.</li>
					<li>Click a layer to select it, then jog with ◀ ▶ (or arrow keys) until the door is fully open, and press <b>Lock open</b>.</li>
					<li>Jog until it's fully closed, then press <b>Lock closed</b>.</li>
					<li>A layer can only sort once both angles are locked in.</li>
				</ol>
			</div>
		</Alert>
	{:else}
		<div class="text-sm text-text-muted">
			Click a layer to control it with the arrow keys. Jog each door to its open and closed
			positions and lock in the angles — a layer must have both angles locked before it will move
			during sorting.
		</div>
	{/if}

	{#if backend === 'pca9685'}
		<ServoSpeedSettings
			bind:openSpeed
			bind:closeSpeed
			bind:homingSpeed
			disabled={loading || saving}
		/>
	{/if}

	{#if backend === 'waveshare'}
		<Alert variant="warning">
			This calibrator is for the PCA9685 (PWM) servo backend. The current machine is configured for
			the Waveshare bus.
		</Alert>
	{:else}
		<div class="flex flex-wrap items-center gap-3">
			<label class="flex items-center gap-2 text-sm text-text">
				Jog step (°)
				<input
					type="number"
					min="1"
					max="45"
					step="1"
					bind:value={jogStep}
					class="setup-control w-16 px-2 py-1.5 text-text"
				/>
			</label>
			<button
				onclick={addLayer}
				disabled={loading || saving}
				class="inline-flex items-center gap-1.5 border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				<Plus size={14} /> Add layer
			</button>
		</div>

		{#if layers.length === 0 && !loading}
			<div class="text-sm text-text-muted">No storage layers configured.</div>
		{/if}

		<div class="flex flex-col gap-3">
			{#each layers as layer (layer.layerIndex)}
				{@const calibrated = layerIsCalibrated(layer)}
				{@const selected = selectedIndex === layer.layerIndex}
				<div
					role="button"
					tabindex="0"
					onclick={() => toggleSelect(layer.layerIndex)}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							toggleSelect(layer.layerIndex);
						}
					}}
					class="setup-panel relative flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-2 p-3 transition-colors {selected
						? 'outline! outline-2! outline-offset-2! outline-primary!'
						: 'outline-none hover:border-border'} {layer.enabled ? '' : 'opacity-60'}"
				>
					{#if selected}
						<div
							class="absolute -top-3 right-3 z-10 inline-flex items-center gap-1.5 bg-primary px-2 py-1 text-xs font-medium text-primary-contrast"
						>
							<Keyboard size={13} />
							Use ← → to jog · Esc to deselect
						</div>
					{/if}

					<!-- Label + calibration status -->
					<div class="flex items-center gap-2">
						<span class="text-sm font-semibold text-text">{layer.label}</span>
						{#if calibrated}
							<span class="inline-flex items-center gap-1 bg-success/15 px-2 py-0.5 text-xs font-medium text-success">
								<Lock size={12} /> Calibrated
							</span>
						{:else}
							<span class="inline-flex items-center gap-1 bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
								<LockOpen size={12} /> Needs calibration
							</span>
						{/if}
					</div>

					<div class="h-6 w-px bg-border"></div>

					<!-- Hardware settings -->
					<label class="inline-flex items-center gap-1 text-sm text-text-muted" onclick={(e) => e.stopPropagation()}>
						<Cog size={13} /> Ch
						<select
							value={layer.channel}
							onchange={(event) => setLayer(layer.layerIndex, { channel: event.currentTarget.value })}
							disabled={loading || saving}
							class="setup-control w-14 px-1 py-1 text-text"
						>
							<option value="">-</option>
							{#each channelChoices as choice}
								<option value={String(choice)}>{choice}</option>
							{/each}
						</select>
					</label>
					<label class="inline-flex items-center gap-1.5 text-sm text-text" onclick={(e) => e.stopPropagation()}>
						<input
							class="setup-toggle"
							type="checkbox"
							checked={layer.invert}
							onchange={(event) => setLayer(layer.layerIndex, { invert: event.currentTarget.checked })}
							disabled={loading || saving}
						/>
						Invert
					</label>
					<label class="inline-flex items-center gap-1 text-sm text-text-muted" onclick={(e) => e.stopPropagation()}>
						Bins
						<select
							value={layer.binCount}
							onchange={(event) => setLayer(layer.layerIndex, { binCount: event.currentTarget.value })}
							disabled={loading || saving}
							class="setup-control w-16 px-1 py-1 text-text"
						>
							{#each allowedCounts as count}
								<option value={String(count)}>{count}</option>
							{/each}
						</select>
					</label>
					<label class="inline-flex items-center gap-1 text-sm text-text-muted" onclick={(e) => e.stopPropagation()}>
						Max/bin
						<input
							type="number"
							min="1"
							step="1"
							placeholder="∞"
							value={layer.maxPiecesPerBin}
							oninput={(event) => setLayer(layer.layerIndex, { maxPiecesPerBin: event.currentTarget.value })}
							disabled={loading || saving}
							class="setup-control w-16 px-1 py-1 text-text"
						/>
					</label>

					<div class="h-6 w-px bg-border"></div>

					<!-- Jog + current angle -->
					<div class="inline-flex items-center gap-1" onclick={(e) => e.stopPropagation()}>
						<button
							onclick={() => jog(layer.layerIndex, -jogStep)}
							disabled={loading || saving || layer.busy || !layerHasChannel(layer)}
							class="flex h-8 w-8 items-center justify-center border border-border bg-surface text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
							title="Jog towards lower angle"
						>
							<ChevronLeft size={16} />
						</button>
						<span class="inline-flex items-center gap-1 px-1 text-sm text-text">
							<Crosshair size={13} class="text-text-muted" />
							{layer.currentAngle === null ? 'unknown' : `${layer.currentAngle}°`}
						</span>
						<button
							onclick={() => jog(layer.layerIndex, jogStep)}
							disabled={loading || saving || layer.busy || !layerHasChannel(layer)}
							class="flex h-8 w-8 items-center justify-center border border-border bg-surface text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
							title="Jog towards higher angle"
						>
							<ChevronRight size={16} />
						</button>
					</div>

					<!-- Calibrate -->
					<div class="inline-flex items-center gap-2" onclick={(e) => e.stopPropagation()}>
						<Button
							variant="secondary"
							size="sm"
							onclick={() => lockAngle(layer.layerIndex, 'open')}
							disabled={loading || saving || layer.busy || !layerHasChannel(layer)}
						>
							<LockOpen size={14} /> Lock open
						</Button>
						<Button
							variant="secondary"
							size="sm"
							onclick={() => lockAngle(layer.layerIndex, 'closed')}
							disabled={loading || saving || layer.busy || !layerHasChannel(layer)}
						>
							<Lock size={14} /> Lock closed
						</Button>
						{#if layer.lockStatus === 'saving'}
							<span class="text-sm text-text-muted">Saving…</span>
						{:else if layer.lockStatus === 'saved'}
							<span class="text-sm text-success">Saved</span>
						{:else if layer.lockStatus === 'error'}
							<span class="text-sm text-danger" title={layer.lockError}>Failed</span>
						{/if}
					</div>

					<div class="h-6 w-px bg-border"></div>

					<!-- Open / Close -->
					<div class="inline-flex items-center gap-2" onclick={(e) => e.stopPropagation()}>
						<Button
							variant="ghost"
							size="sm"
							onclick={() => moveTo(layer.layerIndex, layer.openAngle)}
							disabled={loading || saving || layer.busy || layer.openAngle === null}
						>
							<DoorOpen size={14} /> Open
						</Button>
						<Button
							variant="ghost"
							size="sm"
							onclick={() => moveTo(layer.layerIndex, layer.closedAngle)}
							disabled={loading || saving || layer.busy || layer.closedAngle === null}
						>
							<DoorClosed size={14} /> Close
						</Button>
					</div>

					<!-- Angles summary + active + remove, pushed right -->
					<div class="ml-auto flex items-center gap-3">
						<span class="text-sm text-text-muted">
							open {layer.openAngle === null ? 'unknown' : `${layer.openAngle}°`} · closed
							{layer.closedAngle === null ? 'unknown' : `${layer.closedAngle}°`}
						</span>
						<label class="inline-flex items-center gap-2 text-sm text-text" onclick={(e) => e.stopPropagation()}>
							<input
								class="setup-toggle"
								type="checkbox"
								checked={layer.enabled}
								onchange={(event) => setLayer(layer.layerIndex, { enabled: event.currentTarget.checked })}
								disabled={loading || saving}
							/>
							Active
						</label>
						<button
							onclick={(e) => {
								e.stopPropagation();
								removeLayer(layer.layerIndex);
							}}
							disabled={loading || saving}
							class="inline-flex items-center border border-danger/30 bg-danger/[0.06] px-2 py-1.5 text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
							title="Remove {layer.label}"
						>
							<Trash2 size={14} />
						</button>
					</div>

					{#if layer.enabled && !calibrated}
						<div class="w-full text-sm text-warning">
							Lock both the open and closed angles before this layer can sort.
						</div>
					{/if}
				</div>
			{/each}
		</div>

		<div class="flex flex-wrap items-center gap-2">
			<Button variant="primary" size="sm" onclick={saveSettings} loading={saving} disabled={loading}>
				<Save size={14} /> Save servo layers
			</Button>
			<Button variant="secondary" size="sm" onclick={loadSettings} disabled={loading || saving}>
				<RotateCcw size={14} /> Reload
			</Button>
			{#if dirty}
				<span class="inline-flex items-center gap-1 bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
					Unsaved changes — save to apply
				</span>
			{/if}
		</div>
	{/if}

	{#if errorMsg}
		<Alert variant="danger">{errorMsg}</Alert>
	{:else if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
