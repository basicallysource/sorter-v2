<script lang="ts">
	import MachineNameField from '$lib/components/MachineNameField.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';

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
</script>

<Panel>
	<div class="flex max-w-md flex-col gap-4">
		<p class="text-sm text-ink-muted">
			Machine ID <span class="font-mono text-ink">{machineId || '–'}</span>
		</p>
		<Field
			label="Machine name"
			for="setup-machine-name"
			error={nameError ?? undefined}
			help={nameStatus || undefined}
		>
			<MachineNameField
				bind:value={nicknameDraft}
				{backendBaseUrl}
				id="setup-machine-name"
				placeholder="Sorting bench A"
			/>
		</Field>
	</div>
</Panel>
