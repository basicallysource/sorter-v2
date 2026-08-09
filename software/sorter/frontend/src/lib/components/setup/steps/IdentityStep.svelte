<script lang="ts">
	import MachineNameField from '$lib/components/MachineNameField.svelte';

	let {
		machineId,
		nicknameDraft = $bindable(),
		nameError,
		nameStatus,
		backendBaseUrl
	}: {
		machineId: string;
		nicknameDraft: string;
		nameError: string | null;
		nameStatus: string;
		backendBaseUrl: string;
	} = $props();

	const MACHINE_NAME_INPUT_ID = 'setup-machine-name';
</script>

<div class="flex flex-col gap-4">
	<div class="text-xs text-text-muted">
		Machine ID:
		<span class="font-mono text-text">{machineId || '—'}</span>
	</div>
	<div>
		<label for={MACHINE_NAME_INPUT_ID} class="mb-2 block text-sm font-medium text-text">
			Machine name
		</label>
		<MachineNameField
			bind:value={nicknameDraft}
			{backendBaseUrl}
			id={MACHINE_NAME_INPUT_ID}
			placeholder="e.g. Sorting Bench A"
			variant="setup"
		/>
	</div>
	{#if nameError}
		<div class="text-sm text-danger">{nameError}</div>
	{:else if nameStatus}
		<div class="text-sm text-success">{nameStatus}</div>
	{/if}
</div>
