<script lang="ts">
	import { ChevronDown } from 'lucide-svelte';
	import StepperDrvStatusGrid from './StepperDrvStatusGrid.svelte';

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
				Run Current (IRUN): {tmcIrun}
				<input type="range" min="0" max="31" bind:value={tmcIrun} class="w-full" />
			</label>

			<label class="flex flex-col gap-1 text-xs text-text">
				Hold Current (IHOLD): {tmcIhold}
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
