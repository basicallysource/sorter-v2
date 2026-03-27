<script lang="ts">
	import CarouselControlSection from '$lib/components/settings/CarouselControlSection.svelte';
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
		{#if data.station.slug === 'carousel'}
			<div class="w-full lg:max-w-[50%]">
				<SectionCard>
					<CarouselControlSection stepperKey={data.station.stepperKeys[0] ?? 'carousel'} />
				</SectionCard>
			</div>
		{:else}
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
		{/if}
	{/if}
</div>
