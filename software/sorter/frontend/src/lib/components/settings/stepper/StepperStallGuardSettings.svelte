<!--
	One motor's stall detection: on or off, how hard it must be loaded to count
	as a stall (SGTHRS), and the speed floor under which the driver stops
	looking (TCOOLTHRS). It is the same form in the motor's driver settings and
	on its StallGuard tab. The parent pads it and saves it. While automatic
	tuning is on, the threshold and floor are its, shown and not edited.
-->
<script lang="ts">
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import { speedAtTstep, tstepAtSpeed } from '$lib/settings/stallguard';

	let {
		sgEnabled = $bindable(),
		sgThrs = $bindable(),
		sgTcoolthrs = $bindable(),
		microsteps,
		cruiseSpeed = null,
		tuneHref = undefined,
		auto = false
	}: {
		sgEnabled: boolean;
		sgThrs: number;
		sgTcoolthrs: number;
		// The driver's microstepping, for working out the TSTEP a speed gives.
		microsteps: number;
		// The speed this motor cruises at, in µsteps/s, where the page knows it
		// (the chute's operating speed); null where it does not.
		cruiseSpeed?: number | null;
		// Where the threshold is tuned, when this form is not already there.
		tuneHref?: string;
		// Automatic tuning sets the threshold and the speed floor.
		auto?: boolean;
	} = $props();

	// The driver checks for a stall only while TSTEP (its time per 1/256 step)
	// is at or under TCOOLTHRS. A motor that cruises slower than that never
	// reaches the check.
	const cruiseTstep = $derived(
		cruiseSpeed && cruiseSpeed > 0 ? tstepAtSpeed(cruiseSpeed, microsteps) : null
	);
	const minimumSpeed = $derived(sgTcoolthrs > 0 ? speedAtTstep(sgTcoolthrs, microsteps) : null);
	const tooSlowToTrip = $derived(
		sgEnabled && !auto && cruiseTstep !== null && cruiseTstep > sgTcoolthrs
	);
</script>

{#snippet tune()}
	<Button size="sm" href={tuneHref}>Tune StallGuard</Button>
{/snippet}

<div>
	<Checkbox bind:checked={sgEnabled}
		><span class="font-medium">StallGuard stall detection</span></Checkbox
	>
	<p class="mt-0.5 ml-6.5 text-sm text-ink-muted">
		Halts the machine if this motor stalls, on every move while it's on.{#if tuneHref}
			Tune the threshold on the StallGuard tab.{/if}
	</p>
	{#if sgEnabled}
		<div class="mt-3 ml-6.5 flex flex-col gap-3 rounded-control bg-well p-3">
			{#if auto}
				<p class="text-sm text-ink">
					Set by automatic tuning{#if tuneHref}, on the StallGuard tab{/if}.
				</p>
			{:else}
				<div class="flex items-center justify-between gap-3">
					<label for="tmc-sgthrs" class="text-sm text-ink">Threshold (SGTHRS)</label>
					<div class="flex items-center gap-2">
						<input
							type="range"
							min="0"
							max="255"
							bind:value={sgThrs}
							aria-label="Threshold"
							class="w-28 accent-primary"
						/>
						<Input
							id="tmc-sgthrs"
							type="number"
							size="sm"
							min={0}
							max={255}
							bind:value={sgThrs}
							class="w-20"
						/>
					</div>
				</div>
				<div class="flex items-center justify-between gap-3">
					<label for="tmc-tcoolthrs" class="text-sm text-ink">Speed floor (TCOOLTHRS)</label>
					<Input
						id="tmc-tcoolthrs"
						type="number"
						size="sm"
						min={0}
						bind:value={sgTcoolthrs}
						unit="TSTEP"
						class="w-32"
					/>
				</div>
			{/if}
			<p class="num text-sm text-ink-muted">
				Trips when SG_RESULT is {sgThrs * 2} or less, only at cruising speed (TSTEP up to {sgTcoolthrs}).
			</p>
			{#if tooSlowToTrip}
				<Alert
					tone="warning"
					title="StallGuard can't trip at this speed"
					actions={tuneHref ? tune : undefined}
				>
					At {cruiseSpeed?.toLocaleString()} µsteps/s and 1/{microsteps} microstepping this motor cruises
					at TSTEP {cruiseTstep}, slower than the speed floor of {sgTcoolthrs}, so the driver never
					checks for a stall.
					{#if minimumSpeed !== null}
						It needs an operating speed of at least {minimumSpeed.toLocaleString()} µsteps/s, and then
						a threshold tuned at that speed.
					{/if}
				</Alert>
			{/if}
		</div>
	{/if}
</div>
