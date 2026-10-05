<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Lock from '@lucide/svelte/icons/lock';
	import LockOpen from '@lucide/svelte/icons/lock-open';
	import Layers from '@lucide/svelte/icons/layers';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash';
	import Eraser from '@lucide/svelte/icons/eraser';
	import ServoSpeedSettings from './ServoSpeedSettings.svelte';
	import ChuteFlapDiagram from './ChuteFlapDiagram.svelte';
	import FlapOpenIcon from './FlapOpenIcon.svelte';
	import FlapClosedIcon from './FlapClosedIcon.svelte';
	import { userConfig } from '$lib/stores/userConfig.svelte';
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
	import Switch from '$lib/components/ui/Switch.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';

	type ServoBackend = 'pca9685' | 'waveshare';

	type LayerDraft = {
		layerIndex: number; // 0-based, matches backend layer/servo index
		label: string;
		enabled: boolean;
		channel: string; // PCA channel id as string ('' = unassigned)
		// The channel as last loaded from the backend; null for a layer added here.
		savedChannel: string | null;
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
	// Channel, invert, the jog step and the speeds: set once when the machine is
	// built, so they stay out of the way of calibrating.
	let advanced = $derived(userConfig.servoAdvanced);

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
			return "Choose the channel its servo is wired to (under Advanced), save the layers, then home the machine to move its flap.";
		}
		if (layer.savedChannel !== layer.channel) {
			return 'Save the layers, then home the machine to move its flap.';
		}
		return 'Home the machine to move its flap.';
	}

	// What to do next on a layer that is not calibrated yet: open first, then closed.
	function nextStep(layer: LayerDraft): 'open' | 'closed' | null {
		if (layer.openAngle === null) return 'open';
		if (layer.closedAngle === null) return 'closed';
		return null;
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
					savedChannel: channel && typeof channel.id === 'number' ? String(channel.id) : '',
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
		selectedIndex = layerIndex;
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
						throw new Error(`${layer.label}'s bin limit must be a whole number above 0.`);
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
				savedChannel: null,
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

{#snippet flapStep(layer: LayerDraft, which: 'open' | 'closed', canMove: boolean, idle: boolean)}
	{@const angle = which === 'open' ? layer.openAngle : layer.closedAngle}
	{@const next = nextStep(layer) === which}
	<div class="flex min-w-0 flex-col gap-1.5">
		<span class="text-sm text-ink">
			<span class="font-medium">{which === 'open' ? 'Open' : 'Closed'}</span>
			{#if angle === null}
				<span class="text-ink-muted">· not set</span>
			{:else}
				<span class="num text-ink-muted">· {angle}°</span>
			{/if}
		</span>
		<div class="flex flex-wrap items-center gap-1.5">
			<Button
				size="sm"
				variant={next && canMove ? 'primary' : 'secondary'}
				icon={which === 'open' ? FlapOpenIcon : FlapClosedIcon}
				disabled={idle || !canMove}
				onclick={() => lockAngle(layer.layerIndex, which)}
			>
				{which === 'open' ? 'Lock open' : 'Lock closed'}
			</Button>
			<Button
				size="sm"
				disabled={idle || !canMove || angle === null}
				onclick={() => moveTo(layer.layerIndex, angle)}
			>
				{which === 'open' ? 'Go to open' : 'Go to closed'}
			</Button>
		</div>
	</div>
{/snippet}

{#if backend === 'waveshare'}
	<Alert tone="warning">
		This calibrator is for the PCA9685 (PWM) servo backend, and this machine is set up for the
		Waveshare bus.
	</Alert>
{:else}
	<Panel title="Each layer's flap">
		<div class="flex flex-col gap-4 md:flex-row md:items-start md:gap-8">
			<div class="flex items-center gap-4">
				<ChuteFlapDiagram state="open" size={128} />
				<p class="max-w-56 text-sm text-ink-muted">
					<span class="font-medium text-ink">Open.</span> The flap lies flat in the chute wall, so
					pieces fall past it to the layers below.
				</p>
			</div>
			<div class="flex items-center gap-4">
				<ChuteFlapDiagram state="closed" size={128} />
				<p class="max-w-56 text-sm text-ink-muted">
					<span class="font-medium text-ink">Closed.</span> The flap crosses the chute, so pieces
					slide down this layer's funnel into its bins.
				</p>
			</div>
		</div>
		<p class="mt-4 text-sm text-ink-muted">
			For each layer, move its flap with the arrows (or the arrow keys) until it looks like the
			picture, then lock that angle: open first, then closed. A layer sorts once both are locked.
		</p>
	</Panel>

	<Panel title="Layers" flush>
		{#snippet actions()}
			{#if advanced}
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
			{/if}
			<Switch
				checked={advanced}
				labelledby="storage-layers-advanced"
				onchange={(on) => userConfig.setServoAdvanced(on)}
			/>
			<span id="storage-layers-advanced" class="text-sm text-ink">Advanced</span>
			<Button size="sm" icon={Plus} disabled={loading || saving} onclick={addLayer}>Add a layer</Button>
		{/snippet}

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
				{@const step = nextStep(layer)}
				<!-- Using a layer's arrows selects it; then the arrow keys move its flap. -->
				<div
					class="flex flex-col gap-3 px-(--pad-panel) py-(--pad-row)
						{selected ? 'bg-primary-soft' : ''} {layer.enabled ? '' : 'opacity-60'}"
				>
					<div class="flex flex-wrap items-center gap-2">
						<span class="text-sm font-semibold text-ink">{layer.label}</span>
						{#if !layer.enabled}
							<Badge>Off</Badge>
						{:else if calibrated}
							<Badge tone="success"><Lock size={12} /> Calibrated</Badge>
						{:else}
							<Badge tone="warning"><LockOpen size={12} /> Needs calibrating</Badge>
						{/if}
						{#if selected && canMove}
							<Badge tone="primary">The arrow keys move its flap; Escape lets go</Badge>
						{/if}
						<span class="ml-auto flex items-center gap-3">
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

					<div class="flex flex-wrap items-end gap-x-5 gap-y-3">
						<Field
							label="Bins"
							for="layer-{layer.layerIndex}-bins"
							info="How many bins sit around the chute on this layer. Match the bins fitted on it: {allowedCounts.join(', ')}."
						>
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
						<Field
							label="Bin limit"
							for="layer-{layer.layerIndex}-max"
							info="The most pieces one bin on this layer takes. When a bin reaches it, the machine counts that bin full and sends the category's next pieces to another bin. Leave it empty for no limit."
						>
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
						{#if advanced}
							<Field
								label="Channel"
								for="layer-{layer.layerIndex}-channel"
								info="The servo output on the control board that this layer's flap servo is plugged into."
							>
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
						{/if}
					</div>

					<div class="flex flex-col gap-3 rounded-item bg-well p-3">
						<div class="flex flex-wrap items-center gap-x-8 gap-y-4">
							<div class="flex flex-col gap-1.5">
								<span class="text-sm font-medium text-ink">Flap</span>
								<div
									role="group"
									aria-label="Move the flap of {layer.label}"
									class="flex h-(--size-control-sm) items-stretch divide-x divide-line-strong overflow-hidden rounded-button border border-line-strong bg-field"
								>
									<button
										type="button"
										aria-label="Move toward a lower angle"
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
										aria-label="Move toward a higher angle"
										disabled={idle || !canMove}
										onclick={() => jog(layer.layerIndex, jogStep)}
										class="flex w-(--size-control-sm) items-center justify-center text-ink transition-colors hover:bg-hover focus-visible:-outline-offset-2 disabled:pointer-events-none disabled:opacity-45"
									>
										<ChevronRight size={16} />
									</button>
								</div>
							</div>
							{@render flapStep(layer, 'open', canMove, idle)}
							{@render flapStep(layer, 'closed', canMove, idle)}
							{#if layer.openAngle !== null || layer.closedAngle !== null}
								<Button
									variant="ghost"
									size="sm"
									icon={Eraser}
									class="ml-auto self-end"
									disabled={idle || !canMove}
									onclick={() => clearAngles(layer.layerIndex)}
								>
									Start over
								</Button>
							{/if}
						</div>

						{#if hint || step || layer.lockStatus !== 'idle'}
							<div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
								{#if hint}
									<p class="text-sm text-ink-muted">{hint}</p>
								{:else if step === 'open'}
									<p class="text-sm text-ink">
										Move the flap until it lies flat in the chute wall, then lock it open.
									</p>
								{:else if step === 'closed'}
									<p class="text-sm text-ink">
										Now move the flap until it crosses the chute, then lock it closed.
									</p>
								{/if}
								{#if layer.lockStatus === 'saving'}
									<span class="flex items-center gap-1.5 text-sm text-ink-muted"><Spinner size={12} /> Saving</span>
								{:else if layer.lockStatus === 'saved'}
									<span class="text-sm text-success-ink">Saved</span>
								{:else if layer.lockStatus === 'error'}
									<span class="text-sm text-danger-ink" title={layer.lockError}>Not saved</span>
								{/if}
							</div>
						{/if}
					</div>
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

	{#if advanced}
		<ServoSpeedSettings bind:openSpeed bind:closeSpeed bind:homingSpeed disabled={loading || saving} />
	{/if}
{/if}

{#if errorMsg}
	<Alert tone="danger">{errorMsg}</Alert>
{:else if statusMsg}
	<p class="text-sm text-ink-muted">{statusMsg}</p>
{/if}
