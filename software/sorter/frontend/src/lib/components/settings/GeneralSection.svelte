<script lang="ts">
	import { getBackendWsBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { MachineState } from '$lib/machines/types';
	import { settings } from '$lib/stores/settings';

	type MachineSetup = 'classification_channel' | 'manual_carousel';

	type MachineSetupCard = {
		key: MachineSetup;
		title: string;
		description: string;
		detail: string;
	};

	const MACHINE_SETUP_CARDS: MachineSetupCard[] = [
		{
			key: 'classification_channel',
			title: 'Classification Channel',
			description: 'C-Channels + Classification Channel',
			detail:
				'Standard automatic path: C-channel feeding into a dedicated classification C-channel (C4) on the carousel motor port.'
		},
		{
			key: 'manual_carousel',
			title: 'Manual Carousel Feed',
			description: 'Operator-fed carousel',
			detail:
				'Operators place parts directly into the carousel while the downstream classification path stays unchanged. No automatic feeder orchestration.'
		}
	];

	const manager = getMachinesContext();

	let url = $state(`${getBackendWsBase()}/ws`);
	let nicknameDraft = $state('');
	let loadedMachineId = $state('');
	let nameSaving = $state(false);
	let nameError = $state<string | null>(null);
	let nameStatus = $state('');
	let machineSetup = $state<MachineSetup>('classification_channel');
	let loadingMachineSetup = $state(false);
	let savingMachineSetup = $state(false);
	let machineSetupError = $state<string | null>(null);
	let machineSetupStatus = $state('');

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

	function normalizeMachineSetup(value: unknown): MachineSetup {
		return value === 'manual_carousel' ? 'manual_carousel' : 'classification_channel';
	}

	async function loadMachineSetup() {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) {
			machineSetup = 'classification_channel';
			return;
		}

		loadingMachineSetup = true;
		machineSetupError = null;
		machineSetupStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/machine-setup`);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			machineSetup = normalizeMachineSetup(data.setup);
		} catch (e: any) {
			machineSetupError = e.message ?? 'Failed to load machine setup';
		} finally {
			loadingMachineSetup = false;
		}
	}

	async function saveMachineSetup(nextSetup: MachineSetup) {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) {
			machineSetupError = 'Select a connected machine before changing the machine setup.';
			return;
		}

		savingMachineSetup = true;
		machineSetupError = null;
		machineSetupStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/machine-setup`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ setup: nextSetup })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			machineSetup = normalizeMachineSetup(data.setup);
			machineSetupStatus = 'Machine setup saved. Reset and re-home the machine before running.';
		} catch (e: any) {
			machineSetupError = e.message ?? 'Failed to save machine setup';
		} finally {
			savingMachineSetup = false;
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
			machineSetup = 'classification_channel';
			loadingMachineSetup = false;
			savingMachineSetup = false;
			machineSetupError = null;
			machineSetupStatus = '';
			if (machineId) {
				void loadMachineSetup();
			}
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
								? 'border-primary bg-primary/10 dark:bg-primary/10'
								: 'border-border bg-bg'
						}`}
					>
						<div class="flex items-center gap-2">
							<span
								class="h-2 w-2 rounded-full {m.status === 'connected'
									? 'bg-success'
									: 'bg-danger'}"
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
							class="text-xs text-text-muted hover:text-danger dark:hover:text-red-400"
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
				<div class="text-xs text-text-muted">Leave it blank to fall back to the machine ID.</div>
				{#if nameError}
					<div class="text-sm text-danger dark:text-red-400">{nameError}</div>
				{:else if nameStatus}
					<div class="text-sm text-text-muted">{nameStatus}</div>
				{/if}
			</div>
		{:else}
			<div class="text-sm text-text-muted">Connect to a machine to give it a friendly name.</div>
		{/if}
	</div>

	<div>
		<h3 class="mb-2 text-sm font-medium text-text">Machine Setup</h3>
		{#if manager.selectedMachine}
			<div class="flex flex-col gap-3">
				<div class="text-xs text-text-muted">
					Choose which physical sorter topology this machine is currently wired and built for. The
					selected setup controls which hardware path is expected and which homing rules apply.
				</div>
				<div class="grid gap-2 lg:grid-cols-2">
					{#each MACHINE_SETUP_CARDS as card}
						<button
							onclick={() => saveMachineSetup(card.key)}
							disabled={loadingMachineSetup || savingMachineSetup}
							class={`flex flex-col items-start gap-2 border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
								machineSetup === card.key
									? 'border-primary bg-primary/10 text-text'
									: 'border-border bg-bg text-text hover:bg-surface'
							}`}
						>
							<div class="text-sm font-medium">{card.title}</div>
							<div class="text-xs font-medium text-text">{card.description}</div>
							<div class="text-xs text-text-muted">
								{card.detail}
							</div>
						</button>
					{/each}
				</div>
				<div class="text-xs text-text-muted">
					Changing the machine setup persists to the machine TOML and takes effect after `Reset` and
					`Re-Home`.
				</div>
				{#if machineSetupError}
					<div class="text-sm text-danger dark:text-red-400">{machineSetupError}</div>
				{:else if machineSetupStatus}
					<div class="text-sm text-text-muted">{machineSetupStatus}</div>
				{:else if loadingMachineSetup}
					<div class="text-sm text-text-muted">Loading current machine setup...</div>
				{/if}
			</div>
		{:else}
			<div class="text-sm text-text-muted">
				Connect to a machine before changing the machine setup.
			</div>
		{/if}
	</div>

	<div>
		<h3 class="mb-2 text-sm font-medium text-text">Theme</h3>
		<div class="grid grid-cols-2 gap-2">
			<button
				onclick={() => settings.setTheme('light')}
				class="flex-1 border px-4 py-2 text-sm transition-colors {$settings.theme === 'light'
					? 'border-primary bg-primary/20 text-primary'
					: 'border-border bg-bg text-text hover:bg-surface'}"
			>
				Light
			</button>
			<button
				onclick={() => settings.setTheme('dark')}
				class="flex-1 border px-4 py-2 text-sm transition-colors {$settings.theme === 'dark'
					? 'border-primary bg-primary/20 text-primary'
					: 'border-border bg-bg text-text hover:bg-surface'}"
			>
				Dark
			</button>
		</div>
	</div>
</div>
