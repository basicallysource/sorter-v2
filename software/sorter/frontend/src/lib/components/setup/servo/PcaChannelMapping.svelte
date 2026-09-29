<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	let {
		layerCount,
		pcaChoices,
		layerByAssignment = $bindable(),
		invertByLayer,
		openAngle = $bindable(),
		closedAngle = $bindable(),
		openAngleByLayer = $bindable(),
		closedAngleByLayer = $bindable(),
		nudgeDegrees = $bindable(),
		selectedLayerIdx,
		estimatedAngleByLayer,
		onSetInvert,
		onNudgeLayer,
		onSelectLayer
	}: {
		layerCount: number;
		pcaChoices: number[];
		layerByAssignment: Record<number, number>;
		invertByLayer: Record<number, boolean>;
		openAngle: number;
		closedAngle: number;
		openAngleByLayer: Record<number, string>;
		closedAngleByLayer: Record<number, string>;
		nudgeDegrees: number;
		selectedLayerIdx: number | null;
		estimatedAngleByLayer: Record<number, number>;
		onSetInvert: (layerIdx: number, value: boolean) => void;
		onNudgeLayer: (layerIdx: number, degrees: number) => void;
		onSelectLayer: (layerIdx: number) => void;
	} = $props();
</script>

<div class="setup-panel p-4">
	<div class="text-sm font-semibold text-ink">Default open/close angles</div>
	<div class="mt-1 text-sm text-ink-muted">
		Default angles used for layers that don't have a custom override set below.
	</div>
	<div class="mt-3 grid gap-3 sm:grid-cols-2">
		<label class="flex flex-col gap-1 text-xs text-ink-muted">
			<span>Open angle (°)</span>
			<input
				type="number"
				min="0"
				max="180"
				bind:value={openAngle}
				class="setup-control px-3 py-2 text-ink"
			/>
		</label>
		<label class="flex flex-col gap-1 text-xs text-ink-muted">
			<span>Closed angle (°)</span>
			<input
				type="number"
				min="0"
				max="180"
				bind:value={closedAngle}
				class="setup-control px-3 py-2 text-ink"
			/>
		</label>
	</div>
</div>

<div class="setup-panel p-4">
	<div class="text-sm font-semibold text-ink">PCA9685 channel mapping</div>
	<div class="mt-1 text-sm text-ink-muted">
		Available channels: {pcaChoices.join(', ')}
	</div>
	<div class="mt-4 overflow-x-auto">
		<table class="min-w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-line text-left text-ink-muted">
					<th class="px-3 py-2 font-medium">Layer</th>
					<th class="px-3 py-2 font-medium">Channel</th>
					<th class="px-3 py-2 font-medium">Invert</th>
					<th class="px-3 py-2 font-medium">Open °</th>
					<th class="px-3 py-2 font-medium">Closed °</th>
					<th class="px-3 py-2 font-medium">Nudge</th>
				</tr>
			</thead>
			<tbody>
				{#each Array.from({ length: layerCount }, (_, i) => i + 1) as layerIdx}
					{@const channelId =
						Object.entries(layerByAssignment).find(
							([, value]) => value === layerIdx
						)?.[0] ?? String(layerIdx - 1)}
					<tr class="border-b border-line">
						<td class="px-3 py-2 text-ink">Layer {layerIdx}</td>
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
								class="setup-control w-full px-2 py-1.5 text-ink"
							>
								{#each pcaChoices as choice}
									<option value={String(choice)}>{choice}</option>
								{/each}
							</select>
						</td>
						<td class="px-3 py-2">
							<label class="inline-flex items-center gap-2 text-ink">
								<input
									class="setup-toggle"
									type="checkbox"
									checked={Boolean(invertByLayer[layerIdx])}
									onchange={(event) =>
										onSetInvert(
											layerIdx,
											(event.currentTarget as HTMLInputElement).checked
										)}
								/>
								<span>{invertByLayer[layerIdx] ? 'Yes' : 'No'}</span>
							</label>
						</td>
						<td class="px-3 py-2">
							<input
								type="number"
								min="0"
								max="180"
								placeholder={String(openAngle)}
								value={openAngleByLayer[layerIdx] ?? ''}
								oninput={(event) => {
									const val = (event.currentTarget as HTMLInputElement).value;
									openAngleByLayer = { ...openAngleByLayer, [layerIdx]: val };
								}}
								class="setup-control w-20 px-2 py-1.5 text-ink"
							/>
						</td>
						<td class="px-3 py-2">
							<input
								type="number"
								min="0"
								max="180"
								placeholder={String(closedAngle)}
								value={closedAngleByLayer[layerIdx] ?? ''}
								oninput={(event) => {
									const val = (event.currentTarget as HTMLInputElement).value;
									closedAngleByLayer = { ...closedAngleByLayer, [layerIdx]: val };
								}}
								class="setup-control w-20 px-2 py-1.5 text-ink"
							/>
						</td>
						<td class="px-3 py-2">
							<div class="flex items-center gap-1">
								<button
									onclick={() => onNudgeLayer(layerIdx, -nudgeDegrees)}
									class="flex h-7 w-7 items-center justify-center border border-line bg-surface text-ink transition-colors hover:bg-hover"
									title="Move left"
								>
									<ChevronLeft size={16} />
								</button>
								<input
									type="number"
									min="1"
									max="180"
									bind:value={nudgeDegrees}
									class="setup-control w-12 px-1 py-1 text-center text-xs text-ink"
								/>
								<button
									onclick={() => onNudgeLayer(layerIdx, nudgeDegrees)}
									class="flex h-7 w-7 items-center justify-center border border-line bg-surface text-ink transition-colors hover:bg-hover"
									title="Move right"
								>
									<ChevronRight size={16} />
								</button>
								<button
									onclick={() => onSelectLayer(layerIdx)}
									class={`ml-1 px-2 py-1 text-xs font-medium transition-colors ${selectedLayerIdx === layerIdx ? 'border border-info bg-info-soft text-info-ink' : 'border border-line bg-surface text-ink-muted hover:bg-hover'}`}
									title="Select to use arrow keys"
								>
									{selectedLayerIdx === layerIdx ? '← → active' : 'keys'}
								</button>
								{#if estimatedAngleByLayer[layerIdx] !== undefined}
									<span class="ml-1 text-sm font-medium text-ink">{estimatedAngleByLayer[layerIdx]}°</span>
								{/if}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
