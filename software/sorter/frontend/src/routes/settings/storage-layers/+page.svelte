<script lang="ts">
	// The storage layers, by how this machine turns their doors. Doors on the
	// control board's own servo cable: each layer's bins, then the doors'
	// set-up. Doors on PWM servos or a USB servo adapter: the calibrator those
	// have always had.
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { getDoors, type Doors } from '$lib/api/doors';
	import { errorMessage } from '$lib/api/http';
	import DoorsSetup from '$lib/components/doors/DoorsSetup.svelte';
	import LayerBins from '$lib/components/layers/LayerBins.svelte';
	import ServoLayerCalibrator from '$lib/components/servo/ServoLayerCalibrator.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	const machine = getMachineContext();
	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());
	let doors = $state<Doors | null>(null);
	let error = $state<string | null>(null);

	async function load() {
		error = null;
		try {
			doors = await getDoors(base);
		} catch (e) {
			error = errorMessage(e, 'The machine did not answer.');
		}
	}

	$effect(() => {
		void base;
		void load();
	});

	const onBus = $derived(doors?.backend === 'bus');
</script>

<svelte:head><title>Sorter - Storage layers</title></svelte:head>

<PageHeader
	title="Storage layers"
	description={onBus
		? "Each layer's bins, and the door in the chute that lets pieces onto it."
		: "Each layer's flap, where it opens and closes, and its bins."}
/>

{#if error}
	<Alert tone="danger" title="Could not read the layers">
		{error}
		{#snippet actions()}<Button size="sm" onclick={load}>Try again</Button>{/snippet}
	</Alert>
{:else if doors === null}
	<div class="flex justify-center py-10"><Spinner /></div>
{:else if onBus}
	<div class="flex flex-col gap-(--gap-panels)">
		<LayerBins {base} fixedBottom={doors.fixed_layer !== null} onsaved={load} />
		<DoorsSetup>
			{#snippet notready()}
				Start it from the menu at the top right (the three dots): Start without homing starts
				the hardware without moving anything.
			{/snippet}
		</DoorsSetup>
	</div>
{:else}
	<ServoLayerCalibrator />
{/if}
