<script lang="ts">
	import { ChevronDown } from 'lucide-svelte';

	let {
		open = $bindable(),
		loading,
		saving,
		homing,
		canceling,
		endstopActiveHigh = $bindable(),
		onToggle,
		onSave
	}: {
		open: boolean;
		loading: boolean;
		saving: boolean;
		homing: boolean;
		canceling: boolean;
		endstopActiveHigh: boolean;
		onToggle: () => void;
		onSave: () => void;
	} = $props();
</script>

<div class="border-t border-border pt-4"></div>

<button
	onclick={onToggle}
	class="flex w-full cursor-pointer items-center justify-between"
>
	<div class="text-sm font-medium text-text">Endstop Settings</div>
	<ChevronDown
		size={16}
		class="text-text-muted transition-transform {open ? 'rotate-180' : ''}"
	/>
</button>

{#if open}
	<div class="text-sm text-text-muted">
		Flip this if the endstop reads backwards.
	</div>

	<label class="flex items-center gap-2 text-sm text-text">
		<input
			type="checkbox"
			checked={endstopActiveHigh}
			onchange={(event) => (endstopActiveHigh = event.currentTarget.checked)}
			disabled={loading || saving || homing || canceling}
		/>
		Endstop active high
	</label>

	<button
		onclick={onSave}
		disabled={loading || saving || homing || canceling}
		class="cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
	>
		{saving ? 'Saving...' : 'Save Endstop Settings'}
	</button>
{/if}
