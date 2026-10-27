<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import StepperPanel from '$lib/components/settings/StepperPanel.svelte';
</script>

<svelte:head><title>Sorter - Chute</title></svelte:head>

<PageHeader
	title="Chute"
	description="Move the chute's stepper by hand, home it, and set its driver."
/>
<StepperPanel
	stepperKey="chute"
	label="Chute stepper"
	endstop={{
		configEndpoint: '/api/hardware-config/chute',
		liveEndpoint: '/api/hardware-config/chute/live',
		homeEndpoint: '/api/hardware-config/chute/calibrate/find-endstop',
		homeCancelEndpoint: '/api/hardware-config/chute/calibrate/cancel'
	}}
/>
