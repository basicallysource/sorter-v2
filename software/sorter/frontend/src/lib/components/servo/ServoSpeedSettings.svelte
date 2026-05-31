<script lang="ts">
	import { Undo2 } from 'lucide-svelte';
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

<div class="border border-border">
	<div class="flex items-center justify-between border-b border-border bg-surface px-3 py-2">
		<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">Servo Speeds</span>
		{#if saveStatus === 'saving'}
			<span class="text-xs text-text-muted">Saving…</span>
		{:else if saveStatus === 'saved'}
			<span class="text-xs text-success">Saved</span>
		{:else if saveStatus === 'error'}
			<span class="text-xs text-danger" title={saveError}>Failed to save</span>
		{/if}
	</div>
	<div class="flex flex-wrap items-center gap-x-6 gap-y-3 p-3">
		{#each [
			{ label: 'Open speed',     get: () => openSpeed,    set: (v: number | null) => { openSpeed = v;    scheduleAutoSave(); } },
			{ label: 'Close speed',    get: () => closeSpeed,   set: (v: number | null) => { closeSpeed = v;   scheduleAutoSave(); } },
			{ label: 'Standard speed', get: () => homingSpeed,  set: (v: number | null) => { homingSpeed = v;  scheduleAutoSave(); } },
		] as entry}
			<div class="flex flex-col gap-1">
				<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">{entry.label}</span>
				<div class="flex items-center gap-1.5">
					<input
						type="number" min="1" max="2000" step="1"
						value={entry.get() ?? FW_DEFAULT}
						oninput={(e) => entry.set(parseSpeed(e.currentTarget.value))}
						{disabled}
						class="setup-control w-24 px-2 py-1.5 text-text"
					/>
					<span class="text-sm text-text-muted">°/s</span>
					{#if entry.get() !== null}
						<button
							onclick={() => entry.set(null)}
							{disabled}
							title="Reset to firmware default ({FW_DEFAULT} °/s)"
							class="inline-flex items-center gap-1 border border-border bg-surface px-2 py-1.5 text-sm text-text-muted hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
						><Undo2 size={13} /> {FW_DEFAULT}</button>
					{/if}
				</div>
			</div>
		{/each}
		<p class="w-full text-sm text-text-muted">
			Applied to all layers. Standard speed is used at startup and for jog.
		</p>
	</div>
</div>
