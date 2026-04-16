<script lang="ts">
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';

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
		onSetInvert: (layerIdx: number, value: boolean) => void;
		onNudgeLayer: (layerIdx: number, degrees: number) => void;
		onSelectLayer: (layerIdx: number) => void;
	} = $props();
</script>

<div class="setup-panel p-4">
	<div class="text-sm font-semibold text-text">Default open/close angles</div>
	<div class="mt-1 text-xs text-text-muted">
		Default angles used for layers that don't have a custom override set below.
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
		Available channels: {pcaChoices.join(', ')}
	</div>
	<div class="mt-4 overflow-x-auto">
		<table class="min-w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-border text-left text-text-muted">
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
								{#each pcaChoices as choice}
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
								class="setup-control w-20 px-2 py-1.5 text-text"
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
								class="setup-control w-20 px-2 py-1.5 text-text"
							/>
						</td>
						<td class="px-3 py-2">
							<div class="flex items-center gap-1">
								<button
									onclick={() => onNudgeLayer(layerIdx, -nudgeDegrees)}
									class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg"
									title="Move left"
								>
									<ChevronLeft size={16} />
								</button>
								<input
									type="number"
									min="1"
									max="180"
									bind:value={nudgeDegrees}
									class="setup-control w-12 px-1 py-1 text-center text-xs text-text"
								/>
								<button
									onclick={() => onNudgeLayer(layerIdx, nudgeDegrees)}
									class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg"
									title="Move right"
								>
									<ChevronRight size={16} />
								</button>
								<button
									onclick={() => onSelectLayer(layerIdx)}
									class={`ml-1 px-2 py-1 text-[10px] font-medium transition-colors ${selectedLayerIdx === layerIdx ? 'border border-info bg-info/10 text-info' : 'border border-border bg-surface text-text-muted hover:bg-bg'}`}
									title="Select to use arrow keys"
								>
									{selectedLayerIdx === layerIdx ? '← → active' : 'keys'}
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
