<script lang="ts">
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	const FW_DEFAULT = 1500;

	let {
		openSpeed = $bindable<number | null>(null),
		closeSpeed = $bindable<number | null>(null),
		homingSpeed = $bindable<number | null>(null),
		disabled = false,
	}: {
		openSpeed: number | null;
		closeSpeed: number | null;
		homingSpeed: number | null;
		disabled?: boolean;
	} = $props();

	const manager = getMachinesContext();

	type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';
	let saveStatus = $state<SaveStatus>('idle');
	let saveError = $state('');
	let saveTimer: ReturnType<typeof setTimeout> | null = null;

	function backendBase(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function parseSpeed(raw: string): number | null {
		const v = raw.trim();
		if (v === '') return null;
		const n = parseInt(v);
		return isNaN(n) ? null : Math.max(1, Math.min(2000, n));
	}

	function scheduleAutoSave() {
		if (saveTimer !== null) clearTimeout(saveTimer);
		saveStatus = 'idle';
		saveTimer = setTimeout(() => void autoSave(), 600);
	}

	async function autoSave() {
		saveStatus = 'saving';
		saveError = '';
		try {
			const res = await fetch(`${backendBase()}/api/hardware-config/servo/speeds`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					open_speed: openSpeed,
					close_speed: closeSpeed,
					homing_speed: homingSpeed,
				}),
			});
			if (!res.ok) throw new Error(await res.text());
			saveStatus = 'saved';
		} catch (e: any) {
			saveStatus = 'error';
			saveError = e.message ?? 'Save failed';
		}
	}
</script>

<Panel title="Servo speeds" description="For every layer. The standard speed is used at startup and for jogging." flush>
	{#snippet actions()}
		{#if saveStatus === 'saving'}
			<span class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Saving</span>
		{:else if saveStatus === 'saved'}
			<span class="text-sm text-success-ink">Saved</span>
		{:else if saveStatus === 'error'}
			<span class="text-sm text-danger-ink" title={saveError}>Not saved</span>
		{/if}
	{/snippet}
	<div class="divide-y divide-line">
		{#each [
			{ id: 'open', label: 'Opening', get: () => openSpeed, set: (v: number | null) => { openSpeed = v; scheduleAutoSave(); } },
			{ id: 'close', label: 'Closing', get: () => closeSpeed, set: (v: number | null) => { closeSpeed = v; scheduleAutoSave(); } },
			{ id: 'standard', label: 'Standard', get: () => homingSpeed, set: (v: number | null) => { homingSpeed = v; scheduleAutoSave(); } }
		] as entry (entry.id)}
			<SettingRow label={entry.label} for="servo-speed-{entry.id}">
				{#if entry.get() !== null}
					<Button
						variant="ghost"
						size="sm"
						icon={Undo2}
						label="Back to the firmware default, {FW_DEFAULT} °/s"
						{disabled}
						onclick={() => entry.set(null)}
					/>
				{/if}
				<Input
					id="servo-speed-{entry.id}"
					type="number"
					min={1}
					max={2000}
					step={1}
					value={entry.get() ?? FW_DEFAULT}
					oninput={(e) => entry.set(parseSpeed((e.currentTarget as HTMLInputElement).value))}
					{disabled}
					unit="°/s"
					class="w-32"
				/>
			</SettingRow>
		{/each}
	</div>
</Panel>
