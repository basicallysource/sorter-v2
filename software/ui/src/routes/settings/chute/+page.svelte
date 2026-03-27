<script lang="ts">
	import ChuteSettingsSection from '$lib/components/settings/ChuteSettingsSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StepperControlSection from '$lib/components/settings/StepperControlSection.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Chute Calibration"
		description="Adjust how the chute maps homed position to the physical bin centers around the ring."
	>
		<ChuteSettingsSection />
	</SectionCard>

	<SectionCard
		title="Chute Control"
		description="Manual chute stepper control and testing for the distribution chute."
	>
		<StepperControlSection steppers={['chute']} title="Chute Stepper" />
	</SectionCard>
</div>
