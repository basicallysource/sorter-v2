<script lang="ts">
	import ServoInventoryCard from './ServoInventoryCard.svelte';

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
		busServos,
		highestSeenId,
		suggestedNextId,
		selectedServoId = $bindable(),
		busyByServoId,
		lastMoveByServoId,
		openAngle,
		closedAngle,
		openAngleByLayer = $bindable(),
		closedAngleByLayer = $bindable(),
		nudgeDegrees = $bindable(),
		servoSetupState,
		unassignedLayers,
		onAssignLayer,
		onPromote,
		onCalibrate,
		onToggleOpenClose,
		onToggleInvert,
		onNudge
	}: {
		busServos: BusServo[];
		highestSeenId: number;
		suggestedNextId: number | null;
		selectedServoId: number | null;
		busyByServoId: Record<number, string>;
		lastMoveByServoId: Record<number, 'open' | 'close' | 'center'>;
		openAngle: number;
		closedAngle: number;
		openAngleByLayer: Record<number, string>;
		closedAngleByLayer: Record<number, string>;
		nudgeDegrees: number;
		servoSetupState: (servo: BusServo) => SetupState;
		unassignedLayers: (currentLayer: number) => number[];
		onAssignLayer: (servoId: number, layer: number) => void;
		onPromote: (servoId: number) => void;
		onCalibrate: (servoId: number) => void;
		onToggleOpenClose: (servoId: number) => void;
		onToggleInvert: (layer: number) => void;
		onNudge: (servoId: number, degrees: number) => void;
	} = $props();
</script>

<div class="setup-panel p-4">
	<div>
		<div class="text-sm font-semibold text-text">Detected servos</div>
		<div class="mt-1 text-sm text-text-muted">
			{busServos.length} on the bus · highest ID ever seen: {highestSeenId || '–'}
			{#if suggestedNextId !== null}
				· next free ID: {suggestedNextId}
			{/if}
		</div>
	</div>

	{#if busServos.length === 0}
		<div class="mt-4 border border-dashed border-border px-4 py-6 text-center text-sm text-text-muted">
			No servos found yet. Connect your first servo — the bus auto-scans every few seconds.
		</div>
	{:else}
		<div class="mt-4 grid gap-3">
			{#each busServos as servo (servo.id)}
				{@const setup = servoSetupState(servo)}
				<ServoInventoryCard
					{servo}
					{setup}
					busy={busyByServoId[servo.id]}
					lastMove={lastMoveByServoId[servo.id]}
					selected={selectedServoId === servo.id}
					unassignedLayers={unassignedLayers(setup.layer)}
					{suggestedNextId}
					{openAngle}
					{closedAngle}
					bind:openAngleByLayer
					bind:closedAngleByLayer
					bind:nudgeDegrees
					onSelect={() => {
						selectedServoId = selectedServoId === servo.id ? null : servo.id;
					}}
					onAssignLayer={(layerIdx) => onAssignLayer(servo.id, layerIdx)}
					onPromote={() => onPromote(servo.id)}
					onCalibrate={() => onCalibrate(servo.id)}
					onToggleOpenClose={() => onToggleOpenClose(servo.id)}
					onToggleInvert={() => onToggleInvert(setup.layer)}
					onNudge={(degrees) => onNudge(servo.id, degrees)}
				/>
			{/each}
		</div>
	{/if}

	<div
		class="mt-4 border border-warning bg-[#FFF7E0] px-4 py-3 text-sm leading-relaxed text-[#7A5A00]"
	>
		<div class="font-semibold text-[#5C4400]">Connect one servo at a time</div>
		<div class="mt-1">
			Brand-new Waveshare servos all ship with the factory ID <span class="font-semibold">1</span>,
			and the bus can only talk to one device at that ID. Plug servos in one by one — as soon
			as a fresh one shows up, we automatically promote it to the next free ID
			{#if suggestedNextId !== null}
				(currently <span class="font-semibold">{suggestedNextId}</span>)
			{/if}
			so you can connect the next servo without a collision.
		</div>
	</div>
</div>
