<script lang="ts">
	import { getBackendWsBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { MachineState } from '$lib/machines/types';
	import { settings } from '$lib/stores/settings';
	import { getCurrentThemeColorId, setThemeColor } from '$lib/stores/themeColor.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import ColorPicker from '$lib/components/ui/ColorPicker.svelte';
	import Plug from '@lucide/svelte/icons/plug';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';

	const manager = getMachinesContext();

	let url = $state(`${getBackendWsBase()}/ws`);
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

	let colorId = $state(getCurrentThemeColorId());
</script>

<Panel title="Connection" description="The machine this page is talking to." flush>
	<div class="divide-y divide-line">
		<div class="px-(--pad-panel) pb-4">
			<Field label="Address" for="machine-address" help="The machine's backend, as ws://host:8000/ws.">
				<div class="flex gap-2">
					<Input
						id="machine-address"
						type="url"
						bind:value={url}
						placeholder="ws://host:port/ws"
						class="min-w-0 flex-1 font-mono"
					/>
					<Button icon={Plug} onclick={handleConnect}>Connect</Button>
				</div>
			</Field>
		</div>
		<div class="px-(--pad-panel) py-4">
			<div class="label">Connected machines</div>
			{#if manager.machines.size > 0}
				<ul class="mt-1 divide-y divide-line">
					{#each [...manager.machines.entries()] as [id, m] (id)}
						{@const chosen = manager.selectedMachineId === id}
						<li class="flex items-center gap-3 py-2">
							<button
								type="button"
								onclick={() => manager.selectMachine(id)}
								aria-pressed={chosen}
								class="flex min-w-0 flex-1 items-center gap-3 rounded-item px-2 py-1.5 text-left transition-colors {chosen
									? 'bg-primary-soft'
									: 'hover:bg-hover'}"
							>
								<span
									class="size-2 shrink-0 rounded-full {m.status === 'connected' ? 'bg-success' : 'bg-danger'}"
									aria-hidden="true"
								></span>
								<span class="min-w-0 flex-1">
									<span class="block truncate text-sm font-medium {chosen ? 'text-primary-ink' : 'text-ink'}">
										{m.identity?.nickname ?? id.slice(0, 8)}
									</span>
									<span class="block truncate font-mono text-sm text-ink-muted">{m.url}</span>
								</span>
							</button>
							<Button size="sm" variant="ghost" onclick={() => manager.disconnect(id)}>Disconnect</Button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="mt-1 text-sm text-ink-muted">No machines connected.</p>
			{/if}
		</div>
	</div>
</Panel>

<Panel title="Machine" flush>
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
</Panel>

<Panel title="Appearance" flush>
	<div class="divide-y divide-line">
		<SettingRow label="Theme" help="Applies at once, on this browser.">
			<SegmentedControl
				label="Theme"
				value={$settings.theme}
				onchange={(mode) => settings.setTheme(mode)}
				options={[
					{ value: 'light', label: 'Light', icon: Sun },
					{ value: 'dark', label: 'Dark', icon: Moon }
				]}
			/>
		</SettingRow>
		<div class="px-(--pad-panel) py-(--pad-row)">
			<div class="text-sm font-medium text-ink">Theme color</div>
			<p class="mt-0.5 text-sm text-ink-muted">
				The LEGO color of buttons, focus rings and the current page, on every browser pointed at
				this machine. Applies at once.
			</p>
			<div class="mt-3 rounded-control bg-well p-4">
				<ColorPicker bind:value={colorId} onchange={(id) => void setThemeColor(id)} />
			</div>
		</div>
		<SettingRow
			label="Setup wizard"
			help="Walk through the hardware, the cameras and the first configuration again."
		>
			<Button href="/setup" icon={ArrowRight}>Open the setup wizard</Button>
		</SettingRow>
	</div>
</Panel>
