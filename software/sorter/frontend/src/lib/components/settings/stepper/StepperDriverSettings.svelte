<script lang="ts">
	import StepperDrvStatusGrid from './StepperDrvStatusGrid.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';

	let {
		loading,
		saving,
		hasEndstop,
		tmcIrun = $bindable(),
		tmcIhold = $bindable(),
		tmcMicrosteps = $bindable(),
		tmcStealthchop = $bindable(),
		tmcCoolstep = $bindable(),
		sgEnabled = $bindable(),
		sgThrs = $bindable(),
		sgTcoolthrs = $bindable(),
		stepperDirectionInverted = $bindable(),
		tmcDrvStatus,
		cruiseSpeed = null,
		onSave
	}: {
		loading: boolean;
		saving: boolean;
		hasEndstop: boolean;
		tmcIrun: number;
		tmcIhold: number;
		tmcMicrosteps: number;
		tmcStealthchop: boolean;
		tmcCoolstep: boolean;
		sgEnabled: boolean;
		sgThrs: number;
		sgTcoolthrs: number;
		stepperDirectionInverted: boolean;
		tmcDrvStatus: Record<string, any> | null;
		// The speed this motor cruises at, in µsteps/s, where the page knows it
		// (the chute's operating speed); null where it does not.
		cruiseSpeed?: number | null;
		onSave: () => void;
	} = $props();

	// The driver checks for a stall only while TSTEP (its time per 1/256 step,
	// in ticks of its nominal 12 MHz clock) is at or under TCOOLTHRS. A motor
	// that cruises slower than that never reaches the check.
	const TMC_CLOCK_HZ = 12_000_000;
	const cruiseTstep = $derived(
		cruiseSpeed && cruiseSpeed > 0
			? Math.round((TMC_CLOCK_HZ * tmcMicrosteps) / (cruiseSpeed * 256))
			: null
	);
	const minimumSpeed = $derived(
		sgTcoolthrs > 0 ? Math.ceil((TMC_CLOCK_HZ * tmcMicrosteps) / (sgTcoolthrs * 256)) : null
	);
	const tooSlowToTrip = $derived(sgEnabled && cruiseTstep !== null && cruiseTstep > sgTcoolthrs);
</script>

{#snippet current(id: string, label: string, help: string, get: () => number, set: (v: number) => void)}
	<SettingRow {label} {help} for={id}>
		<input
			type="range"
			min="0"
			max="31"
			value={get()}
			oninput={(e) => set(Number(e.currentTarget.value))}
			aria-label={label}
			class="w-32 accent-primary"
		/>
		<Input
			{id}
			type="number"
			size="sm"
			min={0}
			max={31}
			value={get()}
			oninput={(e) => set(Number((e.currentTarget as HTMLInputElement).value))}
			class="w-20"
		/>
	</SettingRow>
{/snippet}

{#if loading}
	<div class="flex items-center gap-2 px-(--pad-panel) py-(--pad-row) text-sm text-ink-muted">
		<Spinner size={14} /> Reading the driver
	</div>
{:else}
	<div class="divide-y divide-line">
		{@render current('tmc-irun', 'Run current', 'IRUN, 0 to 31.', () => tmcIrun, (v) => (tmcIrun = v))}
		{@render current('tmc-ihold', 'Hold current', 'IHOLD, 0 to 31.', () => tmcIhold, (v) => (tmcIhold = v))}
		<SettingRow label="Microstepping" for="tmc-microsteps">
			<div class="w-28">
				<Select
					id="tmc-microsteps"
					size="sm"
					value={String(tmcMicrosteps)}
					onchange={(v) => (tmcMicrosteps = Number(v))}
					options={[1, 2, 4, 8, 16, 32, 64, 128, 256].map((ms) => ({ value: String(ms), label: `1/${ms}` }))}
				/>
			</div>
		</SettingRow>
		<div class="flex flex-wrap gap-x-6 gap-y-2 px-(--pad-panel) py-(--pad-row)">
			<Checkbox bind:checked={tmcStealthchop}>StealthChop</Checkbox>
			<Checkbox bind:checked={tmcCoolstep}>CoolStep</Checkbox>
			<Checkbox bind:checked={stepperDirectionInverted}>Invert the direction</Checkbox>
		</div>
		<div class="px-(--pad-panel) py-(--pad-row)">
			<Checkbox bind:checked={sgEnabled}><span class="font-medium">StallGuard stall detection</span></Checkbox>
			<p class="mt-0.5 ml-6.5 text-sm text-ink-muted">
				Halts the machine if this motor stalls, on every move while it's on. Tune the threshold on the
				StallGuard page.
			</p>
			{#if sgEnabled}
				<div class="mt-3 ml-6.5 flex flex-col gap-3 rounded-control bg-well p-3">
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
							<Input id="tmc-sgthrs" type="number" size="sm" min={0} max={255} bind:value={sgThrs} class="w-20" />
						</div>
					</div>
					<div class="flex items-center justify-between gap-3">
						<label for="tmc-tcoolthrs" class="text-sm text-ink">Speed floor (TCOOLTHRS)</label>
						<Input id="tmc-tcoolthrs" type="number" size="sm" min={0} bind:value={sgTcoolthrs} unit="TSTEP" class="w-32" />
					</div>
					<p class="num text-sm text-ink-muted">
						Trips when SG_RESULT is {sgThrs * 2} or less, only at cruising speed (TSTEP up to {sgTcoolthrs}).
					</p>
					{#if tooSlowToTrip}
						<Alert tone="warning" title="StallGuard can't trip at this speed">
							At {cruiseSpeed?.toLocaleString()} µsteps/s and 1/{tmcMicrosteps} microstepping this motor cruises
							at TSTEP {cruiseTstep}, slower than the speed floor of {sgTcoolthrs}, so the driver never checks
							for a stall.
							{#if minimumSpeed !== null}
								It needs an operating speed of at least {minimumSpeed.toLocaleString()} µsteps/s, and then a
								threshold tuned at that speed.
							{/if}
							{#snippet actions()}
								<Button size="sm" href="/settings/stepper-stallguard">Tune StallGuard</Button>
							{/snippet}
						</Alert>
					{/if}
				</div>
			{/if}
		</div>
		<div class="flex justify-end px-(--pad-panel) py-(--pad-row)">
			<Button variant="primary" loading={saving} onclick={onSave}>Apply the driver settings</Button>
		</div>
		{#if tmcDrvStatus}
			<StepperDrvStatusGrid drvStatus={tmcDrvStatus} />
		{/if}
	</div>
{/if}
