<script lang="ts">
	import { machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { MachineState } from '$lib/machines/types';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';

	const manager = getMachinesContext();

	let nicknameDraft = $state('');
	let loadedMachineId = $state('');
	let nameSaving = $state(false);
	let nameError = $state<string | null>(null);
	let nameStatus = $state('');

	function machineHttpBase(machine: MachineState | null): string | null {
		return machineHttpBaseUrlFromWsUrl(machine?.url);
	}

	function normalizedNickname(value: string): string {
		return value.trim();
	}


	async function saveMachineName() {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) {
			nameError = 'Select a connected machine before naming it.';
			return;
		}

		nameSaving = true;
		nameError = null;
		nameStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/machine-identity`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					nickname: normalizedNickname(nicknameDraft) || null
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			nicknameDraft = data.nickname ?? '';
			nameStatus = 'Machine name saved.';
		} catch (e: any) {
			nameError = e.message ?? 'Failed to save machine name';
		} finally {
			nameSaving = false;
		}
	}

	$effect(() => {
		const machineId = manager.selectedMachineId ?? '';
		if (machineId !== loadedMachineId) {
			loadedMachineId = machineId;
			nicknameDraft = manager.selectedMachine?.identity?.nickname ?? '';
			nameSaving = false;
			nameError = null;
			nameStatus = '';
		}
	});
</script>

<Panel title="Machine" flush>
	<div class="divide-y divide-line">
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			{#if manager.selectedMachine}
				<Field
					label="Name"
					for="machine-name"
					help={nameStatus || "Leave it blank to use the machine's ID."}
					error={nameError ?? undefined}
				>
					<div class="flex gap-2">
						<Input
							id="machine-name"
							bind:value={nicknameDraft}
							placeholder="e.g. Bench sorter"
							class="min-w-0 flex-1"
						/>
						<Button
							loading={nameSaving}
							disabled={normalizedNickname(nicknameDraft) ===
								(manager.selectedMachine.identity?.nickname ?? '')}
							onclick={saveMachineName}
						>
							Save name
						</Button>
					</div>
				</Field>
			{:else}
				<p class="text-sm text-ink-muted">Connect to a machine to give it a name.</p>
			{/if}
		</div>
		<SettingRow
			label="Setup wizard"
			help="Walk through the hardware, the cameras and the first configuration again."
		>
			<Button href="/setup" icon={ArrowRight}>Open the setup wizard</Button>
		</SettingRow>
	</div>
</Panel>
