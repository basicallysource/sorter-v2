<script lang="ts">
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';

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

	type SetupState = {
		calibrated: boolean;
		layer: number;
		inverted: boolean;
		isFactory: boolean;
		state: 'factory' | 'needs-calibration' | 'needs-assignment' | 'ready';
		accent: string;
		headerTone: string;
		title: string;
		description: string;
	};

	let {
		servo,
		setup,
		busy,
		lastMove,
		selected,
		unassignedLayers,
		suggestedNextId,
		openAngle,
		closedAngle,
		openAngleByLayer = $bindable(),
		closedAngleByLayer = $bindable(),
		nudgeDegrees = $bindable(),
		onSelect,
		onAssignLayer,
		onPromote,
		onCalibrate,
		onToggleOpenClose,
		onToggleInvert,
		onNudge
	}: {
		servo: BusServo;
		setup: SetupState;
		busy: string | undefined;
		lastMove: 'open' | 'close' | 'center' | undefined;
		selected: boolean;
		unassignedLayers: number[];
		suggestedNextId: number | null;
		openAngle: number;
		closedAngle: number;
		openAngleByLayer: Record<number, string>;
		closedAngleByLayer: Record<number, string>;
		nudgeDegrees: number;
		onSelect: () => void;
		onAssignLayer: (layer: number) => void;
		onPromote: () => void;
		onCalibrate: () => void;
		onToggleOpenClose: () => void;
		onToggleInvert: () => void;
		onNudge: (degrees: number) => void;
	} = $props();

	const calibrated = $derived(setup.calibrated);
	const layer = $derived(setup.layer);
	const inverted = $derived(setup.inverted);
	const isFactory = $derived(setup.isFactory);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class={`overflow-hidden border border-l-4 bg-surface ${setup.accent} ${selected ? 'border-info ring-2 ring-info/30' : 'border-border'}`}
	onclick={onSelect}
>
	<div class={`flex flex-wrap items-start gap-4 px-4 py-3 ${setup.headerTone}`}>
		<div
			class="flex h-12 w-14 shrink-0 flex-col items-center justify-center bg-primary font-bold text-primary-contrast"
		>
			<span class="text-xs uppercase tracking-wider opacity-80">ID</span>
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
			<div class="mt-1 text-sm font-semibold text-text">{setup.title}</div>
			<div class="mt-1 text-sm text-text-muted">{setup.description}</div>
		</div>

		<div class="min-w-[11rem] sm:ml-auto">
			<label class="flex flex-col gap-1">
				<span class="text-xs uppercase tracking-wider text-text-muted">Assigned to</span>
				<select
					value={String(layer)}
					onchange={(event) =>
						onAssignLayer(Number((event.currentTarget as HTMLSelectElement).value))}
					class="setup-control w-full px-3 py-2 text-sm font-medium text-text"
				>
					<option value="0">— Unassigned —</option>
					{#each unassignedLayers as layerOption}
						<option value={String(layerOption)}>Layer {layerOption}</option>
					{/each}
				</select>
			</label>
		</div>
	</div>

	<div class="grid gap-3 border-t border-border px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
		<div>
			<div class="text-xs uppercase tracking-wider text-text-muted">Setup checklist</div>
			<div class="mt-2 flex flex-wrap gap-2 text-xs">
				<span class={`inline-flex items-center gap-1 border px-2 py-1 font-medium ${calibrated ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-bg text-text-muted'}`}>
					<span class={`h-1.5 w-1.5 rounded-full ${calibrated ? 'bg-primary' : 'bg-text-muted'}`}></span>
					{calibrated ? `Calibrated · ${servo.min_limit}–${servo.max_limit}` : 'Calibration pending'}
				</span>
				<span class={`inline-flex items-center gap-1 border px-2 py-1 font-medium ${layer > 0 ? 'border-success/30 bg-success/10 text-success' : 'border-border bg-bg text-text-muted'}`}>
					<span class={`h-1.5 w-1.5 rounded-full ${layer > 0 ? 'bg-success' : 'bg-text-muted'}`}></span>
					{layer > 0 ? `Assigned · Layer ${layer}` : 'Layer not assigned'}
				</span>
				<span class={`inline-flex items-center gap-1 border px-2 py-1 font-medium ${layer > 0 ? 'border-border bg-bg text-text' : 'border-border bg-bg text-text-muted'}`}>
					<span class={`h-1.5 w-1.5 rounded-full ${layer > 0 ? 'bg-text' : 'bg-text-muted'}`}></span>
					Direction {layer > 0 ? (inverted ? 'reversed' : 'normal') : 'set after assignment'}
				</span>
			</div>
		</div>

		{#if isFactory}
			<div class="border border-warning/40 bg-[#FFF7E0] px-3 py-2 text-xs text-[#7A5A00] md:max-w-[18rem]">
				<div class="font-semibold text-[#5C4400]">Factory ID detected</div>
				<div class="mt-1">Promote this servo before plugging in the next one.</div>
				<button
					onclick={onPromote}
					disabled={!!busy}
					class="mt-2 border border-warning bg-warning px-3 py-1.5 text-xs font-semibold text-[#3D2A00] transition-colors hover:bg-warning/90 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{busy === 'promoting' ? 'Promoting…' : `Promote to ID ${suggestedNextId}`}
				</button>
			</div>
		{/if}
	</div>

	{#if layer > 0}
		<div class="border-t border-border bg-bg/40 px-4 py-3">
			<div class="text-xs uppercase tracking-wider text-text-muted">Angle overrides for Layer {layer}</div>
			<div class="mt-2 grid gap-3 sm:grid-cols-2 max-w-sm">
				<label class="flex flex-col gap-1 text-xs text-text-muted">
					<span>Open angle (°)</span>
					<input
						type="number"
						min="0"
						max="180"
						placeholder={String(openAngle)}
						value={openAngleByLayer[layer] ?? ''}
						oninput={(event) => {
							const val = (event.currentTarget as HTMLInputElement).value;
							openAngleByLayer = { ...openAngleByLayer, [layer]: val };
						}}
						class="setup-control px-2 py-1.5 text-text"
					/>
				</label>
				<label class="flex flex-col gap-1 text-xs text-text-muted">
					<span>Closed angle (°)</span>
					<input
						type="number"
						min="0"
						max="180"
						placeholder={String(closedAngle)}
						value={closedAngleByLayer[layer] ?? ''}
						oninput={(event) => {
							const val = (event.currentTarget as HTMLInputElement).value;
							closedAngleByLayer = { ...closedAngleByLayer, [layer]: val };
						}}
						class="setup-control px-2 py-1.5 text-text"
					/>
				</label>
			</div>
			<div class="mt-1 text-sm text-text-muted">Leave blank to use the default angles ({openAngle}° / {closedAngle}°)</div>
		</div>
	{/if}

	<div class="border-t border-border bg-bg/40 px-4 py-3">
		<div class="text-xs uppercase tracking-wider text-text-muted">Actions</div>
		<div class="mt-2 flex flex-wrap items-center gap-2">
			<button
				onclick={onCalibrate}
				disabled={!!busy}
				class={`px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${calibrated ? 'setup-button-secondary text-text' : 'border border-primary bg-primary text-primary-contrast hover:bg-primary-hover'}`}
			>
				{busy === 'calibrating'
					? 'Calibrating…'
					: calibrated
						? 'Recalibrate'
						: 'Auto-calibrate'}
			</button>
			<button
				onclick={onToggleOpenClose}
				disabled={!!busy || !calibrated}
				class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
			>
				{busy === 'moving'
					? 'Testing…'
					: lastMove === 'open'
						? 'Test close'
						: 'Test open'}
			</button>
			<button
				onclick={onToggleInvert}
				disabled={!calibrated || layer === 0}
				title={layer === 0
					? 'Assign a layer first to remember this direction change'
					: 'Use this if the gate opens when it should close'}
				class="setup-button-secondary px-3 py-1.5 text-xs font-medium text-text transition-colors disabled:cursor-not-allowed disabled:opacity-60"
			>
				{inverted ? 'Direction reversed' : 'Reverse direction'}
			</button>
		</div>

		{#if calibrated}
			<div class="mt-3 flex items-center gap-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Nudge</span>
				<button
					onclick={(e) => { e.stopPropagation(); onNudge(-nudgeDegrees); }}
					disabled={!!busy}
					class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-60"
					title="Move left"
				>
					<ChevronLeft size={16} />
				</button>
				<input
					type="number"
					min="1"
					max="180"
					bind:value={nudgeDegrees}
					onclick={(e) => e.stopPropagation()}
					class="setup-control w-14 px-2 py-1 text-center text-xs text-text"
				/>
				<span class="text-xs text-text-muted">°</span>
				<button
					onclick={(e) => { e.stopPropagation(); onNudge(nudgeDegrees); }}
					disabled={!!busy}
					class="flex h-7 w-7 items-center justify-center border border-border bg-surface text-text transition-colors hover:bg-bg disabled:cursor-not-allowed disabled:opacity-60"
					title="Move right"
				>
					<ChevronRight size={16} />
				</button>
				{#if selected}
					<span class="text-xs text-info">Selected — use ←/→ arrow keys</span>
				{:else}
					<span class="text-xs text-text-muted">Click card to use arrow keys</span>
				{/if}
			</div>
		{/if}
	</div>
</div>
