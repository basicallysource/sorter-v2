<script lang="ts">
	import StepperSidebar from '$lib/components/settings/StepperSidebar.svelte';
</script>

<div class="lg:max-w-[20rem]">
	<StepperSidebar
		stepperKey="chute"
		endstop={{
			configEndpoint: '/api/hardware-config/chute',
			liveEndpoint: '/api/hardware-config/chute/live',
			homeEndpoint: '/api/hardware-config/chute/calibrate/find-endstop',
			homeCancelEndpoint: '/api/hardware-config/chute/calibrate/cancel'
		}}
	/>
</div>
