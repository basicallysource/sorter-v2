<script lang="ts">
	import { Plus, Trash2 } from 'lucide-svelte';

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
		enabled: boolean;
		servoId: string;
		invert: boolean;
		maxPiecesPerBin: string;
		liveOpen: boolean | null;
		telemetry: LayerTelemetry;
		testing: boolean;
		calibrating: boolean;
	};

	let {
		layers,
		backend,
		loading,
		saving,
		allowedCounts,
		pcaChannelChoices,
		waveshareServoChoices,
		onAdd,
		onRemove,
		onUpdateCount,
		onUpdateEnabled,
		onUpdateServoId,
		onUpdateInvert,
		onUpdateMaxPieces,
		onToggle,
		onCalibrate
	}: {
		layers: LayerDraft[];
		backend: ServoBackend;
		loading: boolean;
		saving: boolean;
		allowedCounts: number[];
		pcaChannelChoices: number[];
		waveshareServoChoices: number[];
		onAdd: () => void;
		onRemove: (index: number) => void;
		onUpdateCount: (index: number, value: string) => void;
		onUpdateEnabled: (index: number, value: boolean) => void;
		onUpdateServoId: (index: number, value: string) => void;
		onUpdateInvert: (index: number, value: boolean) => void;
		onUpdateMaxPieces: (index: number, value: string) => void;
		onToggle: (index: number) => void;
		onCalibrate: (index: number) => void;
	} = $props();

	function layerHasAssignedServo(layer: LayerDraft): boolean {
		return layer.servoId.trim().length > 0;
	}

	function layerIsOffline(layer: LayerDraft): boolean {
		return backend === 'waveshare' && !layer.telemetry.available && !!layer.telemetry.error;
	}

	function formatTelemetryValue(value: number | null): string {
		return value === null ? '--' : String(value);
	}
</script>

<div class="setup-panel p-4">
	<div class="flex items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<div class="text-sm font-semibold text-text">Layers</div>
			<div class="mt-1 text-sm text-text-muted">
				{layers.length} layer{layers.length !== 1 ? 's' : ''} · bin count, servo mapping, fill
				limit per layer.
			</div>
		</div>
		<button
			onclick={onAdd}
			disabled={loading || saving}
			class="setup-button-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-text disabled:cursor-not-allowed disabled:opacity-50"
		>
			<Plus size={14} />
			Add Layer
		</button>
	</div>

	{#if layers.length === 0 && !loading}
		<div class="mt-4 text-sm text-text-muted">
			No storage layers configured. Add one to get started.
		</div>
	{:else}
		<div class="mt-4 overflow-x-auto">
			<table class="min-w-full border-collapse text-sm">
				<thead>
					<tr class="border-b border-border text-left text-text-muted">
						<th class="px-3 py-2 font-medium">Layer</th>
						<th class="px-3 py-2 font-medium">Active</th>
						<th class="px-3 py-2 font-medium">Bins</th>
						<th class="px-3 py-2 font-medium" title="Max pieces per bin. Empty = unlimited.">
							Max/Bin
						</th>
						<th class="px-3 py-2 font-medium"
							>{backend === 'waveshare' ? 'Servo ID' : 'Channel'}</th
						>
						<th class="px-3 py-2 font-medium">Invert</th>
						{#if backend === 'waveshare'}
							<th class="px-3 py-2 font-medium">Position</th>
						{/if}
						<th class="px-3 py-2 font-medium">State</th>
						<th class="px-3 py-2 text-right font-medium">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each layers as layer, index}
						<tr class="border-b border-border/70 {layer.enabled ? '' : 'opacity-60'}">
							<td class="px-3 py-2 font-medium text-text">Layer {layer.index}</td>
							<td class="px-3 py-2">
								<label class="inline-flex items-center gap-2 text-text">
									<input
										class="setup-toggle"
										type="checkbox"
										checked={layer.enabled}
										onchange={(event) => onUpdateEnabled(index, event.currentTarget.checked)}
										disabled={loading || saving}
										aria-label={`Layer ${layer.index} active`}
									/>
								</label>
							</td>
							<td class="px-3 py-2">
								<select
									value={layer.binCount}
									onchange={(event) => onUpdateCount(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="setup-control w-20 px-2 py-1.5 text-text"
								>
									{#each allowedCounts as count}
										<option value={String(count)}>{count}</option>
									{/each}
								</select>
							</td>
							<td class="px-3 py-2">
								<input
									type="number"
									min="1"
									step="1"
									placeholder="∞"
									value={layer.maxPiecesPerBin}
									oninput={(event) => onUpdateMaxPieces(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="setup-control w-24 px-2 py-1.5 text-text"
									title="Max pieces per bin. Empty = unlimited."
								/>
							</td>
							<td class="px-3 py-2">
								{#if backend === 'waveshare'}
									<select
										value={layer.servoId}
										onchange={(event) => onUpdateServoId(index, event.currentTarget.value)}
										disabled={loading || saving}
										class="setup-control w-24 px-2 py-1.5 text-text"
									>
										<option value="">-</option>
										{#each waveshareServoChoices as servoId}
											<option value={String(servoId)}>{servoId}</option>
										{/each}
									</select>
								{:else}
									<select
										value={layer.servoId}
										onchange={(event) => onUpdateServoId(index, event.currentTarget.value)}
										disabled={loading || saving}
										class="setup-control w-24 px-2 py-1.5 text-text"
									>
										<option value="">-</option>
										{#each pcaChannelChoices as channel}
											<option value={String(channel)}>{channel}</option>
										{/each}
									</select>
								{/if}
							</td>
							<td class="px-3 py-2">
								<label class="inline-flex items-center gap-2 text-text">
									<input
										class="setup-toggle"
										type="checkbox"
										checked={layer.invert}
										onchange={(event) => onUpdateInvert(index, event.currentTarget.checked)}
										disabled={loading || saving || !layer.enabled || !layerHasAssignedServo(layer)}
									/>
								</label>
							</td>
							{#if backend === 'waveshare'}
								<td class="px-3 py-2 font-mono text-sm text-text-muted">
									{#if layerIsOffline(layer)}
										<span class="text-danger dark:text-red-400">Offline</span>
									{:else}
										{formatTelemetryValue(layer.telemetry.position)}
										<span class="text-text-muted/50"
											>/ {formatTelemetryValue(layer.telemetry.openPosition)} · {formatTelemetryValue(
												layer.telemetry.closedPosition
											)}</span
										>
										{#if layer.telemetry.error}
											<span class="ml-1 text-danger" title={layer.telemetry.error}>!</span>
										{/if}
									{/if}
								</td>
							{/if}
							<td class="px-3 py-2">
								{#if !layer.enabled}
									<span
										class="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400"
										title="Inactive layers are ignored when assigning bins."
									>
										<span class="h-1.5 w-1.5 rounded-full bg-amber-500"></span>
										Inactive
									</span>
								{:else if layerIsOffline(layer)}
									<span
										class="inline-flex items-center gap-1 text-xs text-danger dark:text-red-400"
										title={layer.telemetry.error ?? 'Servo offline'}
									>
										<span class="h-1.5 w-1.5 rounded-full bg-danger"></span>
										Offline
									</span>
								{:else if !layerHasAssignedServo(layer)}
									<span
										class="inline-flex items-center gap-1 text-xs text-text-muted"
										title="No servo assigned to this layer."
									>
										<span class="h-1.5 w-1.5 rounded-full bg-border"></span>
										No servo
									</span>
								{:else if layer.liveOpen !== null}
									<span
										class="inline-flex items-center gap-1 text-xs {layer.liveOpen
											? 'text-success dark:text-green-400'
											: 'text-text-muted'}"
									>
										<span
											class="h-1.5 w-1.5 rounded-full {layer.liveOpen
												? 'bg-success'
												: 'bg-border'}"
										></span>
										{layer.liveOpen ? 'Open' : 'Closed'}
									</span>
								{:else}
									<span class="text-xs text-text-muted">--</span>
								{/if}
							</td>
							<td class="px-3 py-2 text-right">
								<div class="flex items-center justify-end gap-1.5">
									<button
										onclick={() => onToggle(index)}
										disabled={loading ||
											saving ||
											layer.testing ||
											!layer.enabled ||
											!layerHasAssignedServo(layer) ||
											layerIsOffline(layer)}
										class="setup-button-secondary px-3 py-1.5 text-sm font-medium text-text disabled:cursor-not-allowed disabled:opacity-50"
									>
										{#if layer.testing}
											…
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
											onclick={() => onCalibrate(index)}
											disabled={loading ||
												saving ||
												layer.calibrating ||
												!layer.enabled ||
												!layerHasAssignedServo(layer) ||
												layerIsOffline(layer)}
											class="setup-button-secondary px-3 py-1.5 text-sm font-medium text-text disabled:cursor-not-allowed disabled:opacity-50"
										>
											{layer.calibrating ? 'Calibrating…' : 'Calibrate'}
										</button>
									{/if}
									<button
										onclick={() => onRemove(index)}
										disabled={loading || saving}
										class="inline-flex items-center gap-1 border border-danger/30 bg-danger/[0.06] px-2.5 py-1.5 text-sm text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
										title="Remove layer {layer.index}"
									>
										<Trash2 size={14} />
									</button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
