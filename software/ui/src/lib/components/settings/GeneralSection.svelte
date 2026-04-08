<script lang="ts">
	import { backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { MachineState } from '$lib/machines/types';
	import { settings } from '$lib/stores/settings';

	type FeedingMode = 'auto_channels' | 'manual_carousel';

	const manager = getMachinesContext();

	let url = $state(`${backendWsBaseUrl}/ws`);
	let nicknameDraft = $state('');
	let loadedMachineId = $state('');
	let nameSaving = $state(false);
	let nameError = $state<string | null>(null);
	let nameStatus = $state('');
	let feedingMode = $state<FeedingMode>('auto_channels');
	let loadingFeedingMode = $state(false);
	let savingFeedingMode = $state(false);
	let feedingModeError = $state<string | null>(null);
	let feedingModeStatus = $state('');

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

	async function loadFeedingMode() {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) {
			feedingMode = 'auto_channels';
			return;
		}

		loadingFeedingMode = true;
		feedingModeError = null;
		feedingModeStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/feeding-mode`);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			feedingMode = data.mode === 'manual_carousel' ? 'manual_carousel' : 'auto_channels';
		} catch (e: any) {
			feedingModeError = e.message ?? 'Failed to load feeding mode';
		} finally {
			loadingFeedingMode = false;
		}
	}

	async function saveFeedingMode(nextMode: FeedingMode) {
		const machine = manager.selectedMachine;
		const httpBase = machineHttpBase(machine);
		if (!machine || !httpBase) {
			feedingModeError = 'Select a connected machine before changing the feeding mode.';
			return;
		}

		savingFeedingMode = true;
		feedingModeError = null;
		feedingModeStatus = '';
		try {
			const res = await fetch(`${httpBase}/api/feeding-mode`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ mode: nextMode })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			feedingMode = data.mode === 'manual_carousel' ? 'manual_carousel' : 'auto_channels';
			feedingModeStatus = 'Feeding mode saved. Reset and re-home the machine before running.';
		} catch (e: any) {
			feedingModeError = e.message ?? 'Failed to save feeding mode';
		} finally {
			savingFeedingMode = false;
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
			feedingMode = 'auto_channels';
			loadingFeedingMode = false;
			savingFeedingMode = false;
			feedingModeError = null;
			feedingModeStatus = '';
			if (machineId) {
				void loadFeedingMode();
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
				<div class="text-xs text-text-muted">Leave it blank to fall back to the machine ID.</div>
				{#if nameError}
					<div class="text-sm text-[#D01012] dark:text-red-400">{nameError}</div>
				{:else if nameStatus}
					<div class="text-sm text-text-muted">{nameStatus}</div>
				{/if}
			</div>
		{:else}
			<div class="text-sm text-text-muted">Connect to a machine to give it a friendly name.</div>
		{/if}
	</div>

	<div>
		<h3 class="mb-2 text-sm font-medium text-text">Feeding Mode</h3>
		{#if manager.selectedMachine}
			<div class="flex flex-col gap-3">
				<div class="text-xs text-text-muted">
					Choose whether this machine feeds parts through the C-Channels automatically or waits for
					an operator to place a part directly into the carousel dropzone.
				</div>
				<div class="grid gap-2 sm:grid-cols-2">
					<button
						onclick={() => saveFeedingMode('auto_channels')}
						disabled={loadingFeedingMode || savingFeedingMode}
						class={`flex flex-col items-start gap-1 border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
							feedingMode === 'auto_channels'
								? 'border-primary bg-primary/10 text-text'
								: 'border-border bg-bg text-text hover:bg-surface'
						}`}
					>
						<span class="text-sm font-medium">Automatic Feed</span>
						<span class="text-xs text-text-muted">
							Use the normal C-Channel feeder automation path.
						</span>
					</button>
					<button
						onclick={() => saveFeedingMode('manual_carousel')}
						disabled={loadingFeedingMode || savingFeedingMode}
						class={`flex flex-col items-start gap-1 border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
							feedingMode === 'manual_carousel'
								? 'border-primary bg-primary/10 text-text'
								: 'border-border bg-bg text-text hover:bg-surface'
						}`}
					>
						<span class="text-sm font-medium">Manual Carousel Feed</span>
						<span class="text-xs text-text-muted">
							Operators place a part into the carousel dropzone and the machine takes over from
							there.
						</span>
					</button>
				</div>
				<div class="text-xs text-text-muted">
					This setting is persisted in the machine TOML and takes effect after `Reset` and
					`Re-Home`.
				</div>
				{#if feedingModeError}
					<div class="text-sm text-[#D01012] dark:text-red-400">{feedingModeError}</div>
				{:else if feedingModeStatus}
					<div class="text-sm text-text-muted">{feedingModeStatus}</div>
				{:else if loadingFeedingMode}
					<div class="text-sm text-text-muted">Loading current feeding mode...</div>
				{/if}
			</div>
		{:else}
			<div class="text-sm text-text-muted">
				Connect to a machine before changing the feeding mode.
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
