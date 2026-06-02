<script lang="ts">
	import { getBackendWsBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { MachineState } from '$lib/machines/types';
	import { settings } from '$lib/stores/settings';

	type MachineSetup = 'standard_carousel' | 'classification_channel' | 'manual_carousel';

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
				'Replaces the carousel/chamber pair with a dedicated classification C-channel on the former carousel motor port.'
		},
		{
			key: 'standard_carousel',
			title: 'Carousel Setup',
			description: 'FIDA + Carousel + Classification Chamber',
			detail:
				'Uses the current automatic path with C-channel feeding, carousel handoff, and chamber classification.'
		},
		{
			key: 'manual_carousel',
			title: 'Manual Carousel Feed',
			description: 'Operator-fed carousel',
			detail:
				'Skips automatic feeder orchestration and waits for manual part placement into the carousel dropzone.'
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

	let classificationMode = $state('simple_state_machine_rev01');
	let savingClassificationMode = $state(false);
	let classificationModeError = $state<string | null>(null);
	let classificationModeStatus = $state('');

	let feederMode = $state('go_to_angle_rev01');
	let savingFeederMode = $state(false);
	let feederModeError = $state<string | null>(null);
	let feederModeStatus = $state('');

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
		return value === 'standard_carousel' || value === 'manual_carousel'
			? value
			: 'classification_channel';
	}

	function classificationModeLabel(mode: string): string {
		const labels: Record<string, string> = {
			simple_state_machine_rev01: 'Simple State Machine',
			classic_carousel: 'Classic Carousel',
			dynamic: 'Dynamic'
		};
		return labels[mode] ?? mode;
	}

	function feederModeLabel(mode: string): string {
		const labels: Record<string, string> = {
			go_to_angle_rev01: 'Go to Angle',
			pulse_perception_rev01: 'Simple Pulse',
			drop_zone_reactive_rev01: 'Drop Zone Reactive'
		};
		return labels[mode] ?? mode;
	}

	async function loadMachineSetup() {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) {
			machineSetup = 'standard_carousel';
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

	async function loadSubsystemModes() {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) return;
		try {
			const [cRes, fRes] = await Promise.all([
				fetch(`${httpBase}/api/classification-channel-mode`),
				fetch(`${httpBase}/api/feeder-subsystem-mode`)
			]);
			if (cRes.ok) {
				const d = await cRes.json();
				classificationMode = d.mode;
			}
			if (fRes.ok) {
				const d = await fRes.json();
				feederMode = d.mode;
			}
		} catch {}
	}

	async function saveClassificationMode(mode: string) {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) return;
		savingClassificationMode = true;
		classificationModeError = null;
		classificationModeStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/classification-channel-mode`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ mode })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			classificationMode = data.mode;
			classificationModeStatus = 'Saved. Restart the backend for changes to take effect.';
		} catch (e: any) {
			classificationModeError = e.message ?? 'Failed to save classification mode';
		} finally {
			savingClassificationMode = false;
		}
	}

	async function saveFeederMode(mode: string) {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) return;
		savingFeederMode = true;
		feederModeError = null;
		feederModeStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/feeder-subsystem-mode`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ mode })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			feederMode = data.mode;
			feederModeStatus = 'Saved. Restart the backend for changes to take effect.';
		} catch (e: any) {
			feederModeError = e.message ?? 'Failed to save feeder mode';
		} finally {
			savingFeederMode = false;
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
			machineSetupStatus =
				data?.machine_setup?.runtime_supported === false
					? 'Machine setup saved. Reset and re-home the machine before running. Runtime support for this experimental setup is still in progress.'
					: 'Machine setup saved. Reset and re-home the machine before running.';
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
			machineSetup = 'standard_carousel';
			loadingMachineSetup = false;
			savingMachineSetup = false;
			machineSetupError = null;
			machineSetupStatus = '';
			if (machineId) {
				void loadMachineSetup();
				void loadSubsystemModes();
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
				<div class="grid gap-2 lg:grid-cols-3">
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
				{#if machineSetupError}
					<div class="text-sm text-danger dark:text-red-400">{machineSetupError}</div>
				{:else if machineSetupStatus}
					<div class="text-sm text-text-muted">{machineSetupStatus}</div>
				{:else if loadingMachineSetup}
					<div class="text-sm text-text-muted">Loading current machine setup...</div>
				{/if}

				<div class="mt-4 flex flex-col gap-4">
					<div>
						<div class="mb-1.5 text-xs font-medium text-text">Classification Channel Mode</div>
						<div class="flex flex-wrap gap-2">
							{#each ['simple_state_machine_rev01', 'classic_carousel', 'dynamic'] as mode}
								<button
									onclick={() => saveClassificationMode(mode)}
									disabled={savingClassificationMode}
									class={`flex items-center gap-1.5 border px-3 py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
										classificationMode === mode
											? 'border-primary bg-primary/10 text-text'
											: 'border-border bg-bg text-text hover:bg-surface'
									}`}
								>
									{classificationModeLabel(mode)}
									{#if mode === 'simple_state_machine_rev01'}
										<span class="border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.14em] text-primary">
											default
										</span>
									{/if}
								</button>
							{/each}
						</div>
						{#if classificationModeError}
							<div class="mt-1 text-xs text-danger">{classificationModeError}</div>
						{:else if classificationModeStatus}
							<div class="mt-1 text-xs text-text-muted">{classificationModeStatus}</div>
						{/if}
					</div>

					<div>
						<div class="mb-1.5 text-xs font-medium text-text">Feeder Mode</div>
						<div class="flex flex-wrap gap-2">
							{#each ['go_to_angle_rev01', 'pulse_perception_rev01'] as mode}
								<button
									onclick={() => saveFeederMode(mode)}
									disabled={savingFeederMode}
									class={`flex items-center gap-1.5 border px-3 py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
										feederMode === mode
											? 'border-primary bg-primary/10 text-text'
											: 'border-border bg-bg text-text hover:bg-surface'
									}`}
								>
									{feederModeLabel(mode)}
									{#if mode === 'go_to_angle_rev01'}
										<span class="border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.14em] text-primary">
											default
										</span>
									{/if}
								</button>
							{/each}
						</div>
						{#if feederModeError}
							<div class="mt-1 text-xs text-danger">{feederModeError}</div>
						{:else if feederModeStatus}
							<div class="mt-1 text-xs text-text-muted">{feederModeStatus}</div>
						{/if}
					</div>

					<div class="text-xs text-text-muted">
						Changing the machine setup persists to the machine TOML and takes effect after Reset and
						Re-Home.
					</div>
				</div>
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
