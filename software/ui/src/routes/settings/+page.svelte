<script lang="ts">
	import ChuteSettingsSection from '$lib/components/settings/ChuteSettingsSection.svelte';
	import GeneralSection from '$lib/components/settings/GeneralSection.svelte';
	import RuntimeVarsSection from '$lib/components/settings/RuntimeVarsSection.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import ServoSettingsSection from '$lib/components/settings/ServoSettingsSection.svelte';
	import StepperControlSection from '$lib/components/settings/StepperControlSection.svelte';
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Connection & Appearance"
		description="Connect to a machine, manage existing sessions, and set the UI theme."
	>
		<GeneralSection />
	</SectionCard>

	<SectionCard
		title="Runtime Variables"
		description="Adjust live backend tunables that are exposed for the current machine."
	>
		<RuntimeVarsSection />
	</SectionCard>

	<SectionCard
		title="Bins / Servos"
		description="Choose the bin-door servo backend and configure PCA9685 presets or Waveshare bus channels."
	>
		<ServoSettingsSection />
	</SectionCard>

	<SectionCard
		title="Chute Calibration"
		description="Adjust how the chute maps homed position to the physical bin centers around the ring."
	>
		<ChuteSettingsSection />
	</SectionCard>

	<SectionCard
		title="Chute Control"
		description="Manual chute stepper control. This mechanism does not have a dedicated station page yet."
	>
		<StepperControlSection steppers={['chute']} title="Chute Stepper" />
	</SectionCard>
</div>
