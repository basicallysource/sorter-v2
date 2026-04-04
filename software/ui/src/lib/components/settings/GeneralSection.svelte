<script lang="ts">
	import { backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { MachineState } from '$lib/machines/types';
	import { settings } from '$lib/stores/settings';

	const manager = getMachinesContext();

	let url = $state(`${backendWsBaseUrl}/ws`);
	let nicknameDraft = $state('');
	let loadedMachineId = $state('');
	let nameSaving = $state(false);
	let nameError = $state<string | null>(null);
	let nameStatus = $state('');

	function handleConnect() {
		manager.connect(url);
	}

	function machineHttpBase(machine: MachineState | null): string | null {
		return machineHttpBaseUrlFromWsUrl(machine?.url);
	}

	function normalizedNickname(value: string): string {
		return value.trim();
	}

	function selectedMachineLabel(): string {
		return (
			manager.selectedMachine?.identity?.nickname ??
			manager.selectedMachine?.identity?.machine_id.slice(0, 8) ??
			'this machine'
		);
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

<div class="flex flex-col gap-6">
	<div>
		<h3 class="mb-2 text-sm font-medium text-text">Connection</h3>
		<div class="mb-3 flex flex-col gap-2 sm:flex-row">
			<input
				type="text"
				bind:value={url}
				placeholder="ws://host:port/ws"
				class="flex-1 border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
			<button
				onclick={handleConnect}
				class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg"
			>
				Connect
			</button>
		</div>

		{#if manager.machines.size > 0}
			<div class="mb-2 text-xs text-text-muted">
				Connected Machines ({manager.machines.size})
			</div>
			<div class="flex flex-col gap-1">
				{#each [...manager.machines.entries()] as [id, m]}
					<div
						onclick={() => manager.selectMachine(id)}
						onkeydown={(event) => {
							if (event.key === 'Enter' || event.key === ' ') {
								event.preventDefault();
								manager.selectMachine(id);
							}
						}}
						role="button"
						tabindex="0"
						class={`flex items-center justify-between border px-2 py-1.5 ${
							manager.selectedMachineId === id
								? 'border-[#D01012] bg-[#D01012]/10 dark:bg-[#D01012]/10'
								: 'border-border bg-bg'
						}`}
					>
						<div class="flex items-center gap-2">
							<span
								class="h-2 w-2 rounded-full {m.status === 'connected'
									? 'bg-[#00852B]'
									: 'bg-[#D01012]'}"
							></span>
							<span class="text-sm text-text">
								{m.identity?.nickname ?? id.slice(0, 8)}
							</span>
						</div>
						<button
							onclick={(event) => {
								event.stopPropagation();
								manager.disconnect(id);
							}}
							class="text-xs text-text-muted hover:text-[#D01012] dark:hover:text-red-400"
						>
							Disconnect
						</button>
					</div>
				{/each}
			</div>
		{:else}
			<div class="text-sm text-text-muted">No machines connected</div>
		{/if}
	</div>

	<div>
		<h3 class="mb-2 text-sm font-medium text-text">Machine Name</h3>
		{#if manager.selectedMachine}
			<div class="flex flex-col gap-3">
				<div class="text-xs text-text-muted">
					Selected machine:
					<span class="font-medium text-text">{selectedMachineLabel()}</span>
				</div>
				<div class="flex flex-col gap-2 sm:flex-row">
					<input
						type="text"
						bind:value={nicknameDraft}
						placeholder="e.g. Bench Sorter"
						class="flex-1 border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
					<button
						onclick={saveMachineName}
						disabled={nameSaving ||
							normalizedNickname(nicknameDraft) ===
								(manager.selectedMachine.identity?.nickname ?? '')}
						class="cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
					>
						{nameSaving ? 'Saving...' : 'Save Name'}
					</button>
				</div>
				<div class="text-xs text-text-muted">
					Leave it blank to fall back to the machine ID.
				</div>
				{#if nameError}
					<div class="text-sm text-[#D01012] dark:text-red-400">{nameError}</div>
				{:else if nameStatus}
					<div class="text-sm text-text-muted">{nameStatus}</div>
				{/if}
			</div>
		{:else}
			<div class="text-sm text-text-muted">
				Connect to a machine to give it a friendly name.
			</div>
		{/if}
	</div>

	<div>
		<h3 class="mb-2 text-sm font-medium text-text">Theme</h3>
		<div class="grid grid-cols-2 gap-2">
			<button
				onclick={() => settings.setTheme('light')}
				class="flex-1 border px-4 py-2 text-sm transition-colors {$settings.theme === 'light'
					? 'border-[#D01012] bg-[#D01012]/20 text-[#D01012]'
					: 'border-border bg-bg text-text hover:bg-surface'}"
			>
				Light
			</button>
			<button
				onclick={() => settings.setTheme('dark')}
				class="flex-1 border px-4 py-2 text-sm transition-colors {$settings.theme === 'dark'
					? 'border-[#D01012] bg-[#D01012]/20 text-[#D01012]'
					: 'border-border bg-bg text-text hover:bg-surface'}"
			>
				Dark
			</button>
		</div>
	</div>
</div>
