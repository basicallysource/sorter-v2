<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import StepperStallGuard from '$lib/components/settings/StepperStallGuard.svelte';
	import ChutePositionCheck from '$lib/components/settings/stepper/ChutePositionCheck.svelte';
</script>

<svelte:head><title>Sorter - Chute StallGuard</title></svelte:head>

<PageHeader
	title="Chute StallGuard"
	description="Stop the machine when the chute stalls. Tune it by hand in the steps, or let it tune itself."
/>
<div class="flex min-w-0 flex-col gap-(--gap-panels)">
	<ChutePositionCheck />
	<StepperStallGuard
		motor="chute"
		label="the chute"
		operatingSpeedEndpoint="/api/hardware-config/chute"
		stressTestHref="/settings/chute"
	/>
</div>
