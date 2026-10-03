<script lang="ts">
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
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

<SettingRow
	label="Operating speed"
	help="How fast the distributor moves from bin to bin."
	for="chute-operating-speed"
>
	<Input
		id="chute-operating-speed"
		type="number"
		min={1}
		step={100}
		bind:value={chuteOperatingSpeed}
		disabled={loading || saving || homing || canceling}
		unit="µsteps/s"
		class="w-40"
	/>
	<Button loading={saving} disabled={loading || homing || canceling} onclick={onSave}>Save</Button>
</SettingRow>
