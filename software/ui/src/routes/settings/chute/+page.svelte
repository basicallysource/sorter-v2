<script lang="ts">
	import ChuteSettingsSection from '$lib/components/settings/ChuteSettingsSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StepperSidebar from '$lib/components/settings/StepperSidebar.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Chute Calibration"
		description="Adjust how the chute maps homed position to the physical bin centers around the ring."
	>
		<ChuteSettingsSection />
	</SectionCard>

	<div class="lg:max-w-[18rem]">
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
</div>
