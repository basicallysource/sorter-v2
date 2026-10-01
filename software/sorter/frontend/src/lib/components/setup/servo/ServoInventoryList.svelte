<script lang="ts">
	import ServoInventoryCard from './ServoInventoryCard.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

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

<Panel
	title="Servos on the bus"
	description="{busServos.length} on the bus · the highest ID seen is {highestSeenId || '–'}{suggestedNextId !== null ? ` · the next free ID is ${suggestedNextId}` : ''}"
	flush
>
	{#if busServos.length === 0}
		<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">
			No servos found yet. Connect the first one; the bus scans itself every few seconds.
		</p>
	{:else}
		<div class="divide-y divide-line">
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
	{#snippet footer()}
		<div class="mr-auto w-full">
			<Alert tone="warning" title="Connect one servo at a time">
				New Waveshare servos all ship with the factory ID 1, and the bus can only talk to one device
				at that ID. Plug them in one by one: as soon as a new one shows up it is promoted to the next
				free ID{suggestedNextId !== null ? ` (now ${suggestedNextId})` : ''}, so the next one can connect
				without a clash.
			</Alert>
		</div>
	{/snippet}
</Panel>
