<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';

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
		tone?: 'success' | 'warning' | 'primary';
		accent: string;
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

	const estimatedAngleDeg = $derived.by(() => {
		const pos = servo.position;
		const min = servo.min_limit;
		const max = servo.max_limit;
		if (pos == null || min == null || max == null) return null;
		const range = max - min;
		if (range < 20) return null;
		return Math.round((pos - min) * 180 / range);
	});
</script>

<!-- One servo on the bus, a row of the detected list; clicking it selects it
     for the arrow keys. Its left stripe (`setup.accent`) is the hardware state. -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<section
	class="flex flex-col gap-3 border-l-4 py-4 pr-(--pad-panel) pl-[calc(var(--pad-panel)-4px)] transition-colors {setup.accent} {selected
		? 'bg-primary-soft'
		: ''}"
	onclick={onSelect}
>
	<div class="flex flex-wrap items-start gap-4">
		<span class="flex h-12 w-14 shrink-0 flex-col items-center justify-center rounded-control bg-well">
			<span class="text-xs text-ink-muted">ID</span>
			<span class="num text-base leading-none font-semibold text-ink">{servo.id}</span>
		</span>
		<div class="min-w-0 flex-1 text-sm">
			<div class="flex flex-wrap items-baseline gap-x-2">
				<span class="font-medium text-ink">{servo.model_name ?? 'Unknown model'}</span>
				{#if servo.voltage !== null && servo.voltage !== undefined}
					<span class="num text-ink-muted">{servo.voltage} V</span>
				{/if}
			</div>
			<div class="mt-1"><Badge tone={setup.tone} dot>{setup.title}</Badge></div>
			<p class="mt-1 text-ink-muted">{setup.description}</p>
		</div>
		<Field label="Layer" for="servo-layer-{servo.id}" class="w-44 sm:ml-auto">
			<Select
				id="servo-layer-{servo.id}"
				value={String(layer)}
				options={[
					{ value: '0', label: 'Unassigned' },
					...unassignedLayers.map((l) => ({ value: String(l), label: `Layer ${l}` }))
				]}
				onchange={(value) => onAssignLayer(Number(value))}
			/>
		</Field>
	</div>

	<div class="flex flex-wrap gap-2">
		<Badge tone={calibrated ? 'info' : undefined} dot>
			{calibrated ? `Calibrated, ${servo.min_limit} to ${servo.max_limit}` : 'Not calibrated'}
		</Badge>
		<Badge tone={layer > 0 ? 'success' : undefined} dot>
			{layer > 0 ? `Layer ${layer}` : 'No layer'}
		</Badge>
		<Badge dot>
			Direction {layer > 0 ? (inverted ? 'reversed' : 'normal') : 'set after a layer'}
		</Badge>
	</div>

	{#if isFactory}
		<Alert tone="warning" title="Factory ID found">
			Promote this servo before plugging in the next one.
			{#snippet actions()}
				<Button size="sm" loading={busy === 'promoting'} disabled={!!busy} onclick={onPromote}>
					Promote to ID {suggestedNextId}
				</Button>
			{/snippet}
		</Alert>
	{/if}

	{#if layer > 0}
		<div class="rounded-control bg-well p-3">
			<h4 class="label">Angles for layer {layer}</h4>
			<div class="mt-2 grid grid-cols-1 max-w-sm gap-3 sm:grid-cols-2">
				<Field label="Open" for="servo-open-{servo.id}">
					<Input
						id="servo-open-{servo.id}"
						type="number"
						unit="°"
						min={0}
						max={180}
						placeholder={String(openAngle)}
						value={openAngleByLayer[layer] ?? ''}
						oninput={(event) => {
							const val = (event.currentTarget as HTMLInputElement).value;
							openAngleByLayer = { ...openAngleByLayer, [layer]: val };
						}}
					/>
				</Field>
				<Field label="Closed" for="servo-closed-{servo.id}">
					<Input
						id="servo-closed-{servo.id}"
						type="number"
						unit="°"
						min={0}
						max={180}
						placeholder={String(closedAngle)}
						value={closedAngleByLayer[layer] ?? ''}
						oninput={(event) => {
							const val = (event.currentTarget as HTMLInputElement).value;
							closedAngleByLayer = { ...closedAngleByLayer, [layer]: val };
						}}
					/>
				</Field>
			</div>
			<p class="mt-2 text-sm text-ink-muted">
				Blank uses the defaults ({openAngle}° and {closedAngle}°).
			</p>
		</div>
	{/if}

	<div class="flex flex-wrap items-center gap-2">
		<Button
			size="sm"
			variant={calibrated ? 'secondary' : 'primary'}
			loading={busy === 'calibrating'}
			disabled={!!busy}
			onclick={onCalibrate}
		>
			{calibrated ? 'Calibrate again' : 'Calibrate'}
		</Button>
		<Button size="sm" loading={busy === 'moving'} disabled={!!busy || !calibrated} onclick={onToggleOpenClose}>
			{lastMove === 'open' ? 'Test close' : 'Test open'}
		</Button>
		<Button size="sm" disabled={!calibrated || layer === 0} onclick={onToggleInvert}>
			{inverted ? 'Direction reversed' : 'Reverse the direction'}
		</Button>
	</div>
	{#if calibrated && layer === 0}
		<p class="text-sm text-ink-muted">Give it a layer first: the direction is kept for the layer.</p>
	{/if}

	{#if calibrated}
		<div class="flex flex-wrap items-center gap-2 text-sm">
			<span class="text-ink-muted">Nudge</span>
			<Button
				size="sm"
				variant="ghost"
				icon={ChevronLeft}
				label="Move left"
				disabled={!!busy}
				onclick={(e: MouseEvent) => {
					e.stopPropagation();
					onNudge(-nudgeDegrees);
				}}
			/>
			<Input
				size="sm"
				type="number"
				unit="°"
				min={1}
				max={180}
				class="w-20"
				aria-label="Nudge by"
				bind:value={nudgeDegrees}
				onclick={(e) => e.stopPropagation()}
			/>
			<Button
				size="sm"
				variant="ghost"
				icon={ChevronRight}
				label="Move right"
				disabled={!!busy}
				onclick={(e: MouseEvent) => {
					e.stopPropagation();
					onNudge(nudgeDegrees);
				}}
			/>
			<span class={selected ? 'text-info-ink' : 'text-ink-muted'}>
				{selected ? 'Selected: the left and right arrows nudge it.' : 'Click the servo to nudge it with the arrow keys.'}
			</span>
			{#if estimatedAngleDeg !== null}
				<span class="num ml-2 font-medium text-ink">{estimatedAngleDeg}°</span>
			{/if}
		</div>
	{/if}
</section>
