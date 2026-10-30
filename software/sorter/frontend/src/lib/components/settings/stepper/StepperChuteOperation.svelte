<script lang="ts">
	import Panel from '$lib/components/ui/Panel.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import type { Snippet } from 'svelte';

	let {
		loading,
		saving,
		homing,
		canceling,
		chuteOperatingSpeed = $bindable(),
		onSave,
		message
	}: {
		loading: boolean;
		saving: boolean;
		homing: boolean;
		canceling: boolean;
		chuteOperatingSpeed: number;
		onSave: () => void;
		// What the last save said, shown beside the Save button.
		message?: Snippet;
	} = $props();
</script>

<Panel title="Operating speed" description="How fast the distributor moves from bin to bin.">
	<Field label="Speed" for="chute-operating-speed">
		<Input
			id="chute-operating-speed"
			type="number"
			min={1}
			step={100}
			bind:value={chuteOperatingSpeed}
			disabled={loading || saving || homing || canceling}
			unit="µsteps/s"
			class="w-56"
		/>
	</Field>
	{#snippet footer()}
		{#if message}<div class="mr-auto min-w-0 text-sm">{@render message()}</div>{/if}
		<Button
			variant="primary"
			loading={saving}
			disabled={loading || homing || canceling}
			onclick={onSave}
		>
			Save
		</Button>
	{/snippet}
</Panel>
