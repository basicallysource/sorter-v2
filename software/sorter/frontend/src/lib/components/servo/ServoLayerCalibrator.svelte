<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Lock from '@lucide/svelte/icons/lock';
	import LockOpen from '@lucide/svelte/icons/lock-open';
	import DoorOpen from '@lucide/svelte/icons/door-open';
	import DoorClosed from '@lucide/svelte/icons/door-closed';
	import Layers from '@lucide/svelte/icons/layers';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash';
	import Eraser from '@lucide/svelte/icons/eraser';
	import ServoSpeedSettings from './ServoSpeedSettings.svelte';
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';

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
		// Channel of the servo the running hardware drives for this layer; null
		// when it has none (a layer added since the last home).
		liveChannel: number | null;
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

	// The live servos are built when the machine homes, so a layer added or
	// rewired since then can't move until it is saved and the machine homed.
	function layerCanMove(layer: LayerDraft): boolean {
		return layer.liveChannel !== null && layer.channel === String(layer.liveChannel);
	}

	function servoHint(layer: LayerDraft): string | null {
		if (layerCanMove(layer)) return null;
		if (!layerHasChannel(layer)) {
			return "Choose the channel this layer's servo is wired to, save the layers, then home the machine to move it.";
		}
		return 'Save the layers, then home the machine to move this servo.';
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
					liveChannel:
						typeof sl.servo_live_channel === 'number' ? sl.servo_live_channel : null,
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

	async function clearAngles(layerIndex: number) {
		// Reset this layer's calibration back to unknown — both open and closed
		// angles are persisted as null on the backend.
		setLayer(layerIndex, { lockStatus: 'saving', lockError: '' });
		const result = await postLayerAction(layerIndex, 'clear', { which: 'both' });
		if (result) {
			setLayer(layerIndex, {
				openAngle: typeof result.open_angle === 'number' ? result.open_angle : null,
				closedAngle: typeof result.closed_angle === 'number' ? result.closed_angle : null,
				lockStatus: 'idle',
				lockError: ''
			});
			statusMsg = result.message ?? `Layer ${layerIndex + 1} calibration cleared.`;
		} else {
			setLayer(layerIndex, { lockStatus: 'error', lockError: errorMsg ?? 'Clear failed' });
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
				liveChannel: null,
				busy: false,
				lockStatus: 'idle',
				lockError: ''
			}
		];
	}

	function removeLayer(layerIndex: number) {
		layers = layers
			.filter((l) => l.layerIndex !== layerIndex)
			// A layer that shifts down no longer lines up with the live servo at its
			// new index.
			.map((l, i) => ({
				...l,
				layerIndex: i,
				label: `Layer ${i + 1}`,
				liveChannel: i === l.layerIndex ? l.liveChannel : null
			}));
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
			const layer = layers.find((l) => l.layerIndex === selectedIndex);
			if (!layer || !layerCanMove(layer)) return;
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

{#if showDirections}
	<Alert tone="info" title="Calibrate each door servo before sorting">
		<ol class="mt-1 ml-4 list-decimal space-y-0.5">
			<li>Choose the channel this layer's servo is wired to.</li>
			<li>
				Select a layer, then jog it with the arrows (or the arrow keys) until its door is fully open,
				and lock the open angle.
			</li>
			<li>Jog until it's fully closed, then lock the closed angle.</li>
			<li>A layer sorts only once both angles are locked.</li>
		</ol>
	</Alert>
{/if}

{#if backend === 'pca9685'}
	<ServoSpeedSettings bind:openSpeed bind:closeSpeed bind:homingSpeed disabled={loading || saving} />
{/if}

{#if backend === 'waveshare'}
	<Alert tone="warning">
		This calibrator is for the PCA9685 (PWM) servo backend, and this machine is set up for the
		Waveshare bus.
	</Alert>
{:else}
	<Panel
		title="Layers"
		description="Select a layer to jog it with the arrow keys. A layer moves during sorting only once its open and closed angles are both locked."
		flush
	>
		<!-- The panel's own controls, in a row that wraps on a phone. -->
		<div class="flex flex-wrap items-center justify-end gap-2 px-(--pad-panel) pb-3">
			<Input
				type="number"
				min={1}
				max={45}
				step={1}
				bind:value={jogStep}
				unit="° a press"
				size="sm"
				class="w-32"
				aria-label="Jog step"
			/>
			<Button size="sm" icon={Plus} disabled={loading || saving} onclick={addLayer}>Add a layer</Button>
		</div>

		{#if layers.length === 0 && !loading}
			<div class="px-(--pad-panel) pb-(--pad-panel)">
				<EmptyState icon={Layers} title="No storage layers yet">Add a layer to start.</EmptyState>
			</div>
		{:else if loading && layers.length === 0}
			<div class="flex items-center gap-2 px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
				<Spinner size={14} /> Loading the layers
			</div>
		{/if}

		<div class="divide-y divide-line">
			{#each layers as layer (layer.layerIndex)}
				{@const calibrated = layerIsCalibrated(layer)}
				{@const selected = selectedIndex === layer.layerIndex}
				{@const idle = loading || saving || layer.busy}
				{@const canMove = layerCanMove(layer)}
				{@const hint = servoHint(layer)}
				<div
					role="button"
					tabindex="0"
					aria-pressed={selected}
					onclick={() => toggleSelect(layer.layerIndex)}
					onkeydown={(e) => {
						if (e.target !== e.currentTarget) return;
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							toggleSelect(layer.layerIndex);
						}
					}}
					class="flex cursor-pointer flex-col gap-3 px-(--pad-panel) py-(--pad-row) transition-colors
						{selected ? 'bg-primary-soft' : 'hover:bg-hover'} {layer.enabled ? '' : 'opacity-60'}"
				>
					<div class="flex flex-wrap items-center gap-2">
						<span class="text-sm font-semibold text-ink">{layer.label}</span>
						{#if calibrated}
							<Badge tone="success"><Lock size={12} /> Calibrated</Badge>
						{:else}
							<Badge tone="warning"><LockOpen size={12} /> Needs calibrating</Badge>
						{/if}
						{#if selected && canMove}
							<Badge tone="primary">The arrow keys jog it; Escape lets go</Badge>
						{/if}
						<span class="num ml-auto text-sm text-ink-muted">
							Open {layer.openAngle === null ? 'unknown' : `${layer.openAngle}°`}, closed
							{layer.closedAngle === null ? 'unknown' : `${layer.closedAngle}°`}
						</span>
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<span class="flex items-center gap-3" onclick={(e) => e.stopPropagation()}>
							<Checkbox
								checked={layer.enabled}
								disabled={loading || saving}
								onchange={(e) =>
									setLayer(layer.layerIndex, { enabled: (e.currentTarget as HTMLInputElement).checked })}
							>
								Active
							</Checkbox>
							<Button
								variant="ghost"
								size="sm"
								icon={Trash2}
								label="Remove {layer.label}"
								disabled={loading || saving}
								onclick={() => removeLayer(layer.layerIndex)}
							/>
						</span>
					</div>

					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<div class="flex flex-wrap items-end gap-x-5 gap-y-3" onclick={(e) => e.stopPropagation()}>
						<Field label="Channel" for="layer-{layer.layerIndex}-channel">
							<div class="w-24">
								<Select
									id="layer-{layer.layerIndex}-channel"
									size="sm"
									value={layer.channel}
									disabled={loading || saving}
									onchange={(channel) => setLayer(layer.layerIndex, { channel })}
									options={[
										{ value: '', label: 'None' },
										...channelChoices.map((c) => ({ value: String(c), label: String(c) }))
									]}
								/>
							</div>
						</Field>
						<Field label="Bins" for="layer-{layer.layerIndex}-bins">
							<div class="w-20">
								<Select
									id="layer-{layer.layerIndex}-bins"
									size="sm"
									value={layer.binCount}
									disabled={loading || saving}
									onchange={(binCount) => setLayer(layer.layerIndex, { binCount })}
									options={allowedCounts.map((c) => ({ value: String(c), label: String(c) }))}
								/>
							</div>
						</Field>
						<Field label="Most a bin" for="layer-{layer.layerIndex}-max">
							<Input
								id="layer-{layer.layerIndex}-max"
								type="number"
								size="sm"
								min={1}
								step={1}
								placeholder="∞"
								value={layer.maxPiecesPerBin}
								disabled={loading || saving}
								oninput={(e) =>
									setLayer(layer.layerIndex, {
										maxPiecesPerBin: (e.currentTarget as HTMLInputElement).value
									})}
								class="w-24"
							/>
						</Field>
						<div class="pb-1.5">
							<Checkbox
								checked={layer.invert}
								disabled={loading || saving}
								onchange={(e) =>
									setLayer(layer.layerIndex, { invert: (e.currentTarget as HTMLInputElement).checked })}
							>
								Invert
							</Checkbox>
						</div>

						<div class="flex flex-wrap items-center gap-2">
							<div
								role="group"
								aria-label="Jog {layer.label}"
								class="flex h-(--size-control-sm) items-stretch divide-x divide-line-strong overflow-hidden rounded-button border border-line-strong bg-field"
							>
								<button
									type="button"
									aria-label="Jog toward a lower angle"
									disabled={idle || !canMove}
									onclick={() => jog(layer.layerIndex, -jogStep)}
									class="flex w-(--size-control-sm) items-center justify-center text-ink transition-colors hover:bg-hover focus-visible:-outline-offset-2 disabled:pointer-events-none disabled:opacity-45"
								>
									<ChevronLeft size={16} />
								</button>
								<span class="num flex min-w-16 items-center justify-center px-2 text-sm text-ink">
									{layer.currentAngle === null ? 'Unknown' : `${layer.currentAngle}°`}
								</span>
								<button
									type="button"
									aria-label="Jog toward a higher angle"
									disabled={idle || !canMove}
									onclick={() => jog(layer.layerIndex, jogStep)}
									class="flex w-(--size-control-sm) items-center justify-center text-ink transition-colors hover:bg-hover focus-visible:-outline-offset-2 disabled:pointer-events-none disabled:opacity-45"
								>
									<ChevronRight size={16} />
								</button>
							</div>
							<Button
								size="sm"
								icon={LockOpen}
								disabled={idle || !canMove}
								onclick={() => lockAngle(layer.layerIndex, 'open')}
							>
								Lock open
							</Button>
							<Button
								size="sm"
								icon={Lock}
								disabled={idle || !canMove}
								onclick={() => lockAngle(layer.layerIndex, 'closed')}
							>
								Lock closed
							</Button>
							<Button
								variant="ghost"
								size="sm"
								icon={Eraser}
								disabled={idle || !canMove || !layerIsCalibrated(layer)}
								onclick={() => clearAngles(layer.layerIndex)}
							>
								Clear the angles
							</Button>
						</div>

						<div class="flex items-center gap-2">
							<Button
								variant="ghost"
								size="sm"
								icon={DoorOpen}
								disabled={idle || !canMove || layer.openAngle === null}
								onclick={() => moveTo(layer.layerIndex, layer.openAngle)}
							>
								Open
							</Button>
							<Button
								variant="ghost"
								size="sm"
								icon={DoorClosed}
								disabled={idle || !canMove || layer.closedAngle === null}
								onclick={() => moveTo(layer.layerIndex, layer.closedAngle)}
							>
								Close
							</Button>
							{#if layer.lockStatus === 'saving'}
								<span class="flex items-center gap-1.5 text-sm text-ink-muted"><Spinner size={12} /> Saving</span>
							{:else if layer.lockStatus === 'saved'}
								<span class="text-sm text-success-ink">Saved</span>
							{:else if layer.lockStatus === 'error'}
								<span class="text-sm text-danger-ink" title={layer.lockError}>Not saved</span>
							{/if}
						</div>
					</div>

					{#if hint}
						<p class="text-sm text-ink-muted">{hint}</p>
					{/if}
					{#if layer.enabled && !calibrated}
						<p class="text-sm text-warning-ink">
							Lock both the open and the closed angle before this layer can sort.
						</p>
					{/if}
				</div>
			{/each}
		</div>

		{#snippet footer()}
			<div class="flex w-full flex-wrap items-center justify-end gap-2">
				{#if dirty}
					<Badge tone="warning">Unsaved changes</Badge>
				{/if}
				<span class="mr-auto"></span>
				<Button variant="ghost" icon={RotateCcw} disabled={loading || saving} onclick={loadSettings}>
					Reload
				</Button>
				<Button variant="primary" loading={saving} disabled={loading} onclick={saveSettings}>
					Save the layers
				</Button>
			</div>
		{/snippet}
	</Panel>
{/if}

{#if errorMsg}
	<Alert tone="danger">{errorMsg}</Alert>
{:else if statusMsg}
	<p class="text-sm text-ink-muted">{statusMsg}</p>
{/if}
