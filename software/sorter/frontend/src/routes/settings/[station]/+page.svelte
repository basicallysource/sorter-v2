<script lang="ts">
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import C4SectorOccupancyPanel from '$lib/components/settings/C4SectorOccupancyPanel.svelte';
	import StepperSidebar from '$lib/components/settings/StepperSidebar.svelte';
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Sorter - {data.station?.slug ?? 'Settings'}</title></svelte:head>

<div class="flex flex-col gap-6">
	{#if data.station.zoneChannels.length > 0}
		{@const primaryStepperKey = data.station.stepperKeys[0]}
		<SectionCard>
			{#key data.station.slug}
				<ZoneSection
					channels={data.station.zoneChannels}
					stepperKey={primaryStepperKey}
					stepperEndstop={primaryStepperKey
						? data.station.stepperEndstops?.[primaryStepperKey]
						: undefined}
					stepperLabel={primaryStepperKey
						? data.station.stepperDisplay?.[primaryStepperKey]?.label
						: undefined}
					stepperGearRatio={primaryStepperKey
						? data.station.stepperDisplay?.[primaryStepperKey]?.gearRatio
						: undefined}
				/>
			{/key}
		</SectionCard>
		{#if data.station.slug === 'classification-channel'}
			<SectionCard title="C4 Sectors">
				<C4SectorOccupancyPanel />
			</SectionCard>
		{/if}
	{:else if data.station.stepperKeys.length > 0}
		<!-- Stations without cameras (e.g. c-channel-1): show stepper standalone -->
		<div class="lg:max-w-[20rem]">
			{#each data.station.stepperKeys as key, i}
				<StepperSidebar
					stepperKey={key}
					endstop={data.station.stepperEndstops?.[key]}
					label={data.station.stepperDisplay?.[key]?.label}
					gearRatioOverride={data.station.stepperDisplay?.[key]?.gearRatio}
					keyboardShortcuts={i === 0}
				/>
			{/each}
		</div>
	{/if}
</div>
