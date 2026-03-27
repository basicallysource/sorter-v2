<script lang="ts">
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StepperControlSection from '$lib/components/settings/StepperControlSection.svelte';
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<div class="flex flex-col gap-6">
	{#if data.station.zoneChannels.length > 0}
		<SectionCard>
			{#key data.station.slug}
				<ZoneSection channels={data.station.zoneChannels} />
			{/key}
		</SectionCard>
	{/if}

	{#if data.station.stepperKeys.length > 0}
		<div class="grid gap-6 xl:grid-cols-2">
			<SectionCard
				title="Stepper Test / Control"
				description="Manually pulse or stop the mechanism tied to this station."
			>
				<StepperControlSection
					steppers={data.station.stepperKeys}
					title={data.station.label}
					keyboardShortcutStepper={data.station.stepperKeys[0] ?? null}
				/>
			</SectionCard>
		</div>
	{/if}
</div>
