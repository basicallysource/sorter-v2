<script lang="ts">
	// The layer doors' serial servos (DoorsSetup), for a machine whose doors are
	// on the control board's own servo bus. A machine with PWM servo doors sets
	// them up on the Storage layers page.
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { getDoors } from '$lib/api/doors';
	import { errorMessage } from '$lib/api/http';
	import DoorsSetup from '$lib/components/doors/DoorsSetup.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	const machine = getMachineContext();
	let backend = $state<string | null | undefined>(undefined);
	let error = $state<string | null>(null);

	async function load() {
		error = null;
		try {
			const base = machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
			backend = (await getDoors(base)).backend;
		} catch (e) {
			error = errorMessage(e, 'The machine did not answer.');
		}
	}

	$effect(() => {
		void machine.machine?.url;
		void load();
	});

	// Doors on PWM servos; a machine that names none yet may be a new bus one.
	const elsewhere = $derived(backend != null && backend !== 'bus');
</script>

<svelte:head><title>Sorter - Doors</title></svelte:head>

<PageHeader
	title="Doors"
	description="The door on each storage layer: which servo turns it, and where it is shut and where it is open."
/>

{#if error}
	<Alert tone="danger" title="Could not read the doors">
		{error}
		{#snippet actions()}<Button size="sm" onclick={load}>Try again</Button>{/snippet}
	</Alert>
{:else if backend === undefined}
	<div class="flex justify-center py-10"><Spinner /></div>
{:else if elsewhere}
	<Alert tone="info" title="This machine's doors are set up on the Storage layers page">
		Its doors are turned by servos wired to a servo board, not to the control board's own servo
		cable.
		{#snippet actions()}
			<Button size="sm" href="/settings/storage-layers" icon={ArrowRight}>Storage layers</Button>
		{/snippet}
	</Alert>
{:else}
	<DoorsSetup>
		{#snippet notready()}
			Start it from the menu at the top right (the three dots): Start without homing starts the
			hardware without moving anything.
		{/snippet}
	</DoorsSetup>
{/if}
