<!--
	The layer doors' servos, by how this machine turns them. Serial servos on
	the control board's own bus are set up by the doors component, which
	manages itself. PWM servos on a board, and serial servos on a USB adapter,
	keep the setup they had.
-->
<script lang="ts">
	import type { Component } from 'svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import HardwarePower from '$lib/components/setup/HardwarePower.svelte';
	import SetupServoOnboardingSection from '$lib/components/setup/SetupServoOnboardingSection.svelte';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	// The doors setup lives in its own module, built beside this flow; it is
	// looked up rather than imported so this step builds without it.
	const doorsModules = import.meta.glob<{ default: Component }>(
		'/src/lib/components/doors/DoorsSetup.svelte',
		{ eager: true }
	);
	const DoorsSetup = Object.values(doorsModules)[0]?.default ?? null;

	const backend = $derived(flow.summary!.config.servo.backend);
	// A USB servo adapter that answered with servos on it, when the buses were probed.
	const adapterServos = $derived(
		flow.summary!.discovery.usb_devices.find(
			(device) => device.category === 'servo_bus' && (device.servo_count ?? 0) > 0
		)?.servo_count ?? null
	);
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if backend === 'bus'}
		{#if DoorsSetup}
			<DoorsSetup />
		{:else}
			<Alert tone="warning">The doors setup is not part of this build of the software.</Alert>
		{/if}
	{:else}
		<HardwarePower {flow} unlocks="The servos move once the motors are on." />
		<SetupServoOnboardingSection
			initialSource={backend === 'waveshare' ? 'waveshare' : 'pca'}
			{adapterServos}
			onSaved={() => flow.reload()}
		/>
	{/if}
</div>
