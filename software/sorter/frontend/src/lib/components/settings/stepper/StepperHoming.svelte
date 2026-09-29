<script lang="ts">
	import House from '@lucide/svelte/icons/house';
	import Button from '$lib/components/ui/Button.svelte';

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

<div class="flex flex-col gap-3 px-(--pad-panel) py-(--pad-row)">
	<div>
		<div class="text-sm font-medium text-ink">Homing</div>
		<p class="mt-0.5 text-sm text-ink-muted">
			Find the endstop slowly, or cancel and stop every stepper if the wrong motor moves.
		</p>
	</div>
	<div class="flex flex-wrap gap-2">
		<Button icon={House} loading={homing} disabled={loading || saving || canceling} onclick={onHome}>
			Home to the endstop
		</Button>
		<Button variant="danger" loading={canceling} disabled={!homing} onclick={onCancel}>Cancel</Button>
		{#if hasCalibrateEndpoint}
			<Button
				loading={calibrating}
				disabled={endstopTriggered !== true || homing || canceling}
				onclick={onCalibrate}
			>
				Calibrate a full turn
			</Button>
		{/if}
	</div>
	{#if hasCalibrateEndpoint && calibrateResult}
		<p class="num text-sm text-ink-muted">A full turn is {calibrateResult.steps_per_revolution} steps.</p>
	{/if}
</div>
