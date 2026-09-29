<script lang="ts">
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import C4SectorOccupancyPanel from '$lib/components/settings/C4SectorOccupancyPanel.svelte';
	import StepperSidebar from '$lib/components/settings/StepperSidebar.svelte';
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Sorter - {data.station.label}</title></svelte:head>

<PageHeader title={data.station.label} description={data.station.description} />

{#if data.station.zoneChannels.length > 0}
	{@const primaryStepperKey = data.station.stepperKeys[0]}
	{#key data.station.slug}
		<ZoneSection
			channels={data.station.zoneChannels}
			stepperKey={primaryStepperKey}
			stepperEndstop={primaryStepperKey ? data.station.stepperEndstops?.[primaryStepperKey] : undefined}
			stepperLabel={primaryStepperKey
				? data.station.stepperDisplay?.[primaryStepperKey]?.label
				: undefined}
			stepperGearRatio={primaryStepperKey
				? data.station.stepperDisplay?.[primaryStepperKey]?.gearRatio
				: undefined}
		/>
	{/key}
	{#if data.station.slug === 'classification-channel'}
		<C4SectorOccupancyPanel />
	{/if}
{:else if data.station.stepperKeys.length > 0}
	<!-- A station without cameras (C-channel 1): its steppers on their own. -->
	<div class="flex max-w-xl flex-col gap-(--gap-panels)">
		{#each data.station.stepperKeys as key, i (key)}
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
