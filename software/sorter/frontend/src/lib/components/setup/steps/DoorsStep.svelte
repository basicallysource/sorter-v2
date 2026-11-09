<!--
	The layer doors' servos, by how this machine turns them. Serial servos on
	the control board's own bus are set up by the doors component, which
	manages itself. PWM servos on a board, and serial servos on a USB adapter,
	keep the setup they had.
-->
<script lang="ts">
	import Power from '@lucide/svelte/icons/power';
	import Button from '$lib/components/ui/Button.svelte';
	import DoorsSetup from '$lib/components/doors/DoorsSetup.svelte';
	import HardwarePower from '$lib/components/setup/HardwarePower.svelte';
	import SetupServoOnboardingSection from '$lib/components/setup/SetupServoOnboardingSection.svelte';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

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
		<!-- A door set up, or one that stops answering, changes what the summary says is ready. -->
		<DoorsSetup onchange={() => void flow.reload()}>
			{#snippet notready()}
				{#if !flow.hardwareUp}
					<div class="mt-3 flex flex-wrap items-center gap-3">
						<Button
							size="sm"
							icon={Power}
							loading={flow.hardwareBusy}
							onclick={() => void flow.startHardware()}
						>
							Power on the motors
						</Button>
						{#if flow.startError}<span class="text-danger-ink">{flow.startError}</span>{/if}
					</div>
				{/if}
			{/snippet}
		</DoorsSetup>
	{:else}
		<HardwarePower {flow} unlocks="The servos move once the motors are on." />
		<SetupServoOnboardingSection
			initialSource={backend === 'waveshare' ? 'waveshare' : 'pca'}
			{adapterServos}
			onSaved={() => flow.reload()}
		/>
	{/if}
</div>
