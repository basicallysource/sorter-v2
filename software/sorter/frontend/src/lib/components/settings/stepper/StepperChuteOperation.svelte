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

<div class="border-t border-line pt-4"></div>

<div class="flex flex-col gap-1">
	<div class="text-sm font-medium text-ink">Operation</div>
	<div class="text-xs text-ink-muted">
		Normal distributor movement speed during bin-to-bin operation.
	</div>
</div>

<label class="text-xs text-ink">
	Operating Speed (uSteps/s)
	<input
		type="number"
		min="1"
		step="100"
		bind:value={chuteOperatingSpeed}
		disabled={loading || saving || homing || canceling}
		class="mt-1 block w-full border border-line bg-well px-2 py-1.5 text-sm text-ink"
	/>
</label>

<button
	onclick={onSave}
	disabled={loading || saving || homing || canceling}
	class="cursor-pointer border border-line bg-well px-3 py-2 text-sm text-ink transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
>
	{saving ? 'Saving...' : 'Save Operation Settings'}
</button>
