<script lang="ts">
	let {
		loading,
		saving,
		homing,
		canceling,
		chuteOperatingSpeed = $bindable(),
		onSave
	}: {
		loading: boolean;
		saving: boolean;
		homing: boolean;
		canceling: boolean;
		chuteOperatingSpeed: number;
		onSave: () => void;
	} = $props();
</script>

<div class="border-t border-border pt-4"></div>

<div class="flex flex-col gap-1">
	<div class="text-sm font-medium text-text">Operation</div>
	<div class="text-xs text-text-muted">
		Normal distributor movement speed during bin-to-bin operation.
	</div>
</div>

<label class="text-xs text-text">
	Operating Speed (uSteps/s)
	<input
		type="number"
		min="1"
		step="100"
		bind:value={chuteOperatingSpeed}
		disabled={loading || saving || homing || canceling}
		class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
	/>
</label>

<button
	onclick={onSave}
	disabled={loading || saving || homing || canceling}
	class="cursor-pointer border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
>
	{saving ? 'Saving...' : 'Save Operation Settings'}
</button>
