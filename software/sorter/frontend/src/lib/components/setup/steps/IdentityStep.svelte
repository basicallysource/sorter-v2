<!-- The machine's name. Continue saves it. -->
<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import MachineNameField from '$lib/components/MachineNameField.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { errorMessage } from '$lib/api/http';
	import { saveMachineName } from '$lib/api/setup';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	const saved = $derived(flow.summary?.machine.nickname ?? '');
	let draft = $state(untrack(() => flow.summary?.machine.nickname ?? ''));
	let error = $state<string | null>(null);

	async function save(): Promise<boolean> {
		const name = draft.trim();
		if (!name) {
			error = 'Give the machine a name to go on.';
			return false;
		}
		if (name === saved.trim()) return true;
		error = null;
		try {
			await saveMachineName(flow.base, name);
			await flow.reload();
			return true;
		} catch (e) {
			error = errorMessage(e, 'The name was not saved.');
			return false;
		}
	}

	onMount(() => {
		flow.beforeNext = save;
		return () => {
			if (flow.beforeNext === save) flow.beforeNext = null;
		};
	});
</script>

<Panel>
	<div class="flex max-w-md flex-col gap-4">
		<p class="text-sm text-ink-muted">
			Machine ID <span class="font-mono text-ink">{flow.machineId || '–'}</span>
		</p>
		<Field
			label="Machine name"
			for="setup-machine-name"
			error={error ?? undefined}
			help="Saved when you continue."
		>
			<MachineNameField
				bind:value={draft}
				backendBaseUrl={flow.base}
				id="setup-machine-name"
				placeholder="Sorting bench A"
			/>
		</Field>
	</div>
</Panel>
