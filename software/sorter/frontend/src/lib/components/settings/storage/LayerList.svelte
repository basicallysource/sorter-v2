<script lang="ts">
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

<div class="flex items-center justify-between">
	<div class="text-xs text-text-muted">{layers.length} layer{layers.length !== 1 ? 's' : ''}</div>
	<button
		onclick={onAdd}
		disabled={loading || saving}
		class="cursor-pointer border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
	>
		Add Layer
	</button>
</div>

{#if layers.length === 0 && !loading}
	<div class="text-sm text-text-muted">
		No storage layers configured. Add one to get started.
	</div>
{:else}
	<div class="overflow-hidden border border-border">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border bg-surface text-left text-xs">
					<th class="px-3 py-2 font-medium text-text-muted">Layer</th>
					<th class="px-3 py-2 font-medium text-text-muted">Active</th>
					<th class="px-3 py-2 font-medium text-text-muted">Bins</th>
					<th class="px-3 py-2 font-medium text-text-muted">{backend === 'waveshare' ? 'Servo ID' : 'Channel'}</th>
					<th class="px-3 py-2 font-medium text-text-muted">Invert</th>
					{#if backend === 'waveshare'}
						<th class="px-3 py-2 font-medium text-text-muted">Position</th>
					{/if}
					<th class="px-3 py-2 font-medium text-text-muted">State</th>
					<th class="px-3 py-2 text-right font-medium text-text-muted">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each layers as layer, index}
					<tr class="border-b border-border bg-bg last:border-b-0 {layer.enabled ? '' : 'opacity-60'}">
						<td class="px-3 py-2 font-medium text-text">{layer.index}</td>
						<td class="px-3 py-2">
							<input
								type="checkbox"
								checked={layer.enabled}
								onchange={(event) => onUpdateEnabled(index, event.currentTarget.checked)}
								disabled={loading || saving}
								aria-label={`Layer ${layer.index} active`}
							/>
						</td>
						<td class="px-3 py-2">
							<select
								value={layer.binCount}
								onchange={(event) => onUpdateCount(index, event.currentTarget.value)}
								disabled={loading || saving}
								class="w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
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
									onchange={(event) => onUpdateServoId(index, event.currentTarget.value)}
									disabled={loading || saving}
									class="w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
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
									class="w-16 border border-border bg-surface px-1.5 py-1 text-sm text-text"
								>
									<option value="">-</option>
									{#each pcaChannelChoices as channel}
										<option value={String(channel)}>{channel}</option>
									{/each}
								</select>
							{/if}
						</td>
						<td class="px-3 py-2">
							<input
								type="checkbox"
								checked={layer.invert}
								onchange={(event) => onUpdateInvert(index, event.currentTarget.checked)}
								disabled={loading || saving || !layer.enabled || !layerHasAssignedServo(layer)}
							/>
						</td>
						{#if backend === 'waveshare'}
							<td class="px-3 py-2 font-mono text-xs text-text-muted">
								{#if layerIsOffline(layer)}
									<span class="text-danger dark:text-red-400">Offline</span>
								{:else}
									{formatTelemetryValue(layer.telemetry.position)}
									<span class="text-text-muted/50">/ {formatTelemetryValue(layer.telemetry.openPosition)} · {formatTelemetryValue(layer.telemetry.closedPosition)}</span>
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
								<span class="inline-flex items-center gap-1 text-xs {layer.liveOpen ? 'text-success dark:text-green-400' : 'text-text-muted'}">
									<span class="h-1.5 w-1.5 rounded-full {layer.liveOpen ? 'bg-success' : 'bg-border'}"></span>
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
									disabled={loading || saving || layer.testing || !layer.enabled || !layerHasAssignedServo(layer) || layerIsOffline(layer)}
									class="cursor-pointer border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
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
										onclick={() => onCalibrate(index)}
										disabled={loading || saving || layer.calibrating || !layer.enabled || !layerHasAssignedServo(layer) || layerIsOffline(layer)}
										class="cursor-pointer border border-border bg-bg px-2 py-1 text-xs text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
									>
										{layer.calibrating ? '...' : 'Cal'}
									</button>
								{/if}
								<button
									onclick={() => onRemove(index)}
									disabled={loading || saving}
									class="cursor-pointer border border-danger/30 bg-danger/[0.06] px-2 py-1 text-xs text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
									title="Remove layer {layer.index}"
								>
									Del
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}
