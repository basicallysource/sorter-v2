<script lang="ts">
	import { ChevronDown } from 'lucide-svelte';
	import StepperDrvStatusGrid from './StepperDrvStatusGrid.svelte';
	import HoverEditNumber from './HoverEditNumber.svelte';

	let {
		open = $bindable(),
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
		onToggle,
		onSave
	}: {
		open: boolean;
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
		onToggle: () => void;
		onSave: () => void;
	} = $props();
</script>

<div class="border-t border-border pt-4"></div>

<button
	onclick={onToggle}
	class="flex w-full cursor-pointer items-center justify-between"
>
	<div class="text-sm font-medium text-text">Driver Settings</div>
	<ChevronDown
		size={16}
		class="text-text-muted transition-transform {open ? 'rotate-180' : ''}"
	/>
</button>

{#if open}
	{#if loading}
		<div class="text-sm text-text-muted">
			Loading driver state...
		</div>
	{:else}
		<div class="flex flex-col gap-3">
			<label class="flex flex-col gap-1 text-xs text-text">
				<span class="flex items-center gap-1">
					Run Current (IRUN): <HoverEditNumber bind:value={tmcIrun} min={0} max={31} />
				</span>
				<input type="range" min="0" max="31" bind:value={tmcIrun} class="w-full" />
			</label>

			<label class="flex flex-col gap-1 text-xs text-text">
				<span class="flex items-center gap-1">
					Hold Current (IHOLD): <HoverEditNumber bind:value={tmcIhold} min={0} max={31} />
				</span>
				<input type="range" min="0" max="31" bind:value={tmcIhold} class="w-full" />
			</label>

			<label class="flex flex-col gap-1 text-xs text-text">
				Microstepping
				<select
					bind:value={tmcMicrosteps}
					class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
				>
					{#each [1, 2, 4, 8, 16, 32, 64, 128, 256] as ms}
						<option value={ms}>1/{ms}</option>
					{/each}
				</select>
			</label>

			<label class="flex items-center gap-2 text-sm text-text">
				<input type="checkbox" bind:checked={tmcStealthchop} />
				StealthChop
			</label>

			<label class="flex items-center gap-2 text-sm text-text">
				<input type="checkbox" bind:checked={tmcCoolstep} />
				CoolStep
			</label>

			<div class="border border-border bg-bg px-3 py-3">
				<label class="flex items-center gap-2 text-sm text-text">
					<input type="checkbox" bind:checked={sgEnabled} />
					StallGuard stall detection
				</label>
				<div class="mt-1 text-xs text-text-muted">
					Halts the machine if this motor stalls — on every move while enabled. Tune the
					threshold on the StallGuard page (Settings → Helpers).
				</div>
				{#if sgEnabled}
					<div class="mt-3 flex flex-col gap-3">
						<label class="flex flex-col gap-1 text-xs text-text">
							<span class="flex items-center gap-1">
								Threshold (SGTHRS): <HoverEditNumber bind:value={sgThrs} min={0} max={255} />
							</span>
							<input type="range" min="0" max="255" bind:value={sgThrs} class="w-full" />
						</label>
						<label class="flex flex-col gap-1 text-xs text-text">
							Velocity floor (TCOOLTHRS, TSTEP)
							<input
								type="number"
								min="0"
								bind:value={sgTcoolthrs}
								class="border border-border bg-bg px-2 py-1.5 text-sm text-text"
							/>
						</label>
						<div class="text-xs text-text-muted">
							Trips when SG_RESULT ≤ {sgThrs * 2}, only at cruise (TSTEP ≤ {sgTcoolthrs}).
						</div>
					</div>
				{/if}
			</div>

			<label class="flex items-center gap-2 text-sm text-text">
				<input
					type="checkbox"
					checked={stepperDirectionInverted}
					onchange={(event) => (stepperDirectionInverted = event.currentTarget.checked)}
				/>
				Invert stepper direction
			</label>

			<button
				onclick={onSave}
				disabled={saving}
				class="cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
			>
				{saving ? 'Applying...' : 'Apply Driver Settings'}
			</button>

			{#if tmcDrvStatus}
				<StepperDrvStatusGrid drvStatus={tmcDrvStatus} />
			{/if}
		</div>
	{/if}
{/if}
