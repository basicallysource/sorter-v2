<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let firstBinCenter = $state(8.4);
	let pillarWidthDeg = $state(1.9);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			firstBinCenter = Number(payload?.chute?.first_bin_center ?? 8.4);
			pillarWidthDeg = Number(payload?.chute?.pillar_width_deg ?? 1.9);
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load chute settings';
		} finally {
			loading = false;
		}
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					first_bin_center: firstBinCenter,
					pillar_width_deg: pillarWidthDeg
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			firstBinCenter = Number(payload?.settings?.first_bin_center ?? firstBinCenter);
			pillarWidthDeg = Number(payload?.settings?.pillar_width_deg ?? pillarWidthDeg);
			statusMsg = payload?.message ?? 'Chute settings saved.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save chute settings';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});
</script>

<div class="flex flex-col gap-4">
	<div class="dark:text-text-muted-dark text-sm text-text-muted">
		These values define how the chute maps section/bin addresses to real angles after homing.
	</div>

	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
		<label class="dark:text-text-dark text-xs text-text">
			First Bin Center (deg)
			<input
				type="number"
				min="0"
				max="60"
				step="0.1"
				bind:value={firstBinCenter}
				disabled={loading || saving}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
		<label class="dark:text-text-dark text-xs text-text">
			Pillar Width (deg)
			<input
				type="number"
				min="0"
				max="59.9"
				step="0.1"
				bind:value={pillarWidthDeg}
				disabled={loading || saving}
				class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
			/>
		</label>
	</div>

	<div class="flex flex-wrap items-center gap-2">
		<button
			onclick={saveSettings}
			disabled={loading || saving}
			class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{saving ? 'Saving...' : 'Save Chute Settings'}
		</button>
		<button
			onclick={loadSettings}
			disabled={loading || saving}
			class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark cursor-pointer border border-border bg-bg px-3 py-1.5 text-sm text-text hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
		>
			{loading ? 'Loading...' : 'Reload'}
		</button>
	</div>

	{#if errorMsg}
		<div class="text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
