<script lang="ts">
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StepperStallGuardSettings from './StepperStallGuardSettings.svelte';

	// The driver's settings as a divided list of rows. The parent places the
	// Apply button and the driver's status readout, which differ between a motor
	// with a page of its own and one under a camera.
	let {
		loading,
		tmcIrun = $bindable(),
		tmcIhold = $bindable(),
		tmcMicrosteps = $bindable(),
		tmcStealthchop = $bindable(),
		tmcCoolstep = $bindable(),
		sgEnabled = $bindable(),
		sgThrs = $bindable(),
		sgTcoolthrs = $bindable(),
		stepperDirectionInverted = $bindable(),
		cruiseSpeed = null,
		stallguardHref = undefined,
		sgAuto = false
	}: {
		loading: boolean;
		tmcIrun: number;
		tmcIhold: number;
		tmcMicrosteps: number;
		tmcStealthchop: boolean;
		tmcCoolstep: boolean;
		sgEnabled: boolean;
		sgThrs: number;
		sgTcoolthrs: number;
		stepperDirectionInverted: boolean;
		// The speed this motor cruises at, in µsteps/s, where the page knows it
		// (the chute's operating speed); null where it does not.
		cruiseSpeed?: number | null;
		// The motor's StallGuard tab, where it has one.
		stallguardHref?: string;
		// Automatic tuning sets the threshold and the speed floor.
		sgAuto?: boolean;
	} = $props();
</script>

{#snippet current(
	id: string,
	label: string,
	help: string,
	get: () => number,
	set: (v: number) => void
)}
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
		{@render current(
			'tmc-irun',
			'Run current',
			'IRUN, 0 to 31.',
			() => tmcIrun,
			(v) => (tmcIrun = v)
		)}
		{@render current(
			'tmc-ihold',
			'Hold current',
			'IHOLD, 0 to 31.',
			() => tmcIhold,
			(v) => (tmcIhold = v)
		)}
		<SettingRow label="Microstepping" for="tmc-microsteps">
			<div class="w-28">
				<Select
					id="tmc-microsteps"
					size="sm"
					value={String(tmcMicrosteps)}
					onchange={(v) => (tmcMicrosteps = Number(v))}
					options={[1, 2, 4, 8, 16, 32, 64, 128, 256].map((ms) => ({
						value: String(ms),
						label: `1/${ms}`
					}))}
				/>
			</div>
		</SettingRow>
		<div class="flex flex-wrap gap-x-6 gap-y-2 px-(--pad-panel) py-(--pad-row)">
			<Checkbox bind:checked={tmcStealthchop}>StealthChop</Checkbox>
			<Checkbox bind:checked={tmcCoolstep}>CoolStep</Checkbox>
			<Checkbox bind:checked={stepperDirectionInverted}>Invert the direction</Checkbox>
		</div>
		<div class="px-(--pad-panel) py-(--pad-row)">
			<StepperStallGuardSettings
				bind:sgEnabled
				bind:sgThrs
				bind:sgTcoolthrs
				microsteps={tmcMicrosteps}
				{cruiseSpeed}
				tuneHref={stallguardHref}
				auto={sgAuto}
			/>
		</div>
	</div>
{/if}
