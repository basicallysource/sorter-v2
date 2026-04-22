<script lang="ts">
	import { Home } from 'lucide-svelte';

	let {
		loading,
		saving,
		homing,
		canceling,
		calibrating,
		endstopTriggered,
		calibrateResult,
		hasCalibrateEndpoint,
		onHome,
		onCancel,
		onCalibrate
	}: {
		loading: boolean;
		saving: boolean;
		homing: boolean;
		canceling: boolean;
		calibrating: boolean;
		endstopTriggered: boolean | null;
		calibrateResult: { steps_per_revolution: number } | null;
		hasCalibrateEndpoint: boolean;
		onHome: () => void;
		onCancel: () => void;
		onCalibrate: () => void;
	} = $props();
</script>

<div class="border-t border-border pt-4"></div>

<div class="flex flex-col gap-1">
	<div class="text-sm font-medium text-text">Homing</div>
	<div class="text-xs text-text-muted">
		Find the endstop slowly, or cancel and stop all steppers if the wrong motor moves.
	</div>
</div>

<div class="flex flex-col gap-2">
	<button
		onclick={onHome}
		disabled={loading || saving || homing || canceling}
		class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
	>
		<Home size={14} />
		{homing ? 'Homing...' : 'Home to Endstop'}
	</button>
	<button
		onclick={onCancel}
		disabled={!homing || canceling}
		class="cursor-pointer border border-danger bg-danger/20 px-3 py-2 text-sm text-danger hover:bg-danger/30 disabled:cursor-not-allowed disabled:opacity-50"
	>
		{canceling ? 'Canceling...' : 'Cancel Homing'}
	</button>
	{#if hasCalibrateEndpoint}
		<button
			onclick={onCalibrate}
			disabled={endstopTriggered !== true || homing || calibrating || canceling}
			class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
		>
			{calibrating ? 'Calibrating...' : 'Calibrate Full Rotation'}
		</button>
		{#if calibrateResult}
			<div class="text-xs text-text-muted">
				Result: {calibrateResult.steps_per_revolution} steps/rev
			</div>
		{/if}
	{/if}
</div>
