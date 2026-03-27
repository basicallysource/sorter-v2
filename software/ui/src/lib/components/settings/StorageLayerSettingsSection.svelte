<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type LayerDraft = {
		index: number;
		binCount: string;
	};

	const manager = getMachinesContext();

	let loadedMachineKey = $state('');
	let loading = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let allowedCounts = $state<number[]>([12, 18, 30]);
	let layers = $state<LayerDraft[]>([]);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function applySettings(payload: any) {
		const settings = payload?.storage_layers ?? payload?.settings ?? {};
		allowedCounts = Array.isArray(settings?.allowed_bin_counts)
			? settings.allowed_bin_counts.filter((value: unknown): value is number => typeof value === 'number')
			: [12, 18, 30];
		layers = Array.isArray(settings?.layers)
			? settings.layers.map((layer: any, index: number) => ({
					index: Number(layer?.index ?? index + 1),
					binCount: String(Number(layer?.bin_count ?? 12))
				}))
			: [];
	}

	async function loadSettings() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config`);
			if (!res.ok) throw new Error(await res.text());
			applySettings(await res.json());
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load storage layer settings';
		} finally {
			loading = false;
		}
	}

	async function saveSettings() {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const layerBinCounts = layers.map((layer) => {
				const count = Number(layer.binCount);
				if (!allowedCounts.includes(count)) {
					throw new Error(`Layer ${layer.index} must use one of ${allowedCounts.join(', ')} bins.`);
				}
				return count;
			});

			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/storage-layers`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ layer_bin_counts: layerBinCounts })
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			applySettings(payload);
			statusMsg = payload?.message ?? 'Storage layer settings saved.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save storage layer settings';
		} finally {
			saving = false;
		}
	}

	function updateLayerCount(index: number, value: string) {
		layers = layers.map((layer, layerIndex) =>
			layerIndex === index ? { ...layer, binCount: value } : layer
		);
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
		Set how many storage bins each physical layer contains. The current machine supports 12, 18,
		or 30 bins per layer. Saving this layout updates the bin-layout file and requires a backend
		restart to fully apply.
	</div>

	{#if layers.length === 0 && !loading}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">
			No storage layers were found in the current layout file.
		</div>
	{:else}
		<div class="flex flex-col gap-2">
			{#each layers as layer, index}
				<div
					class="dark:border-border-dark dark:bg-bg-dark grid grid-cols-[minmax(0,1fr)_140px] gap-3 border border-border bg-bg px-3 py-2"
				>
					<div class="dark:text-text-dark flex items-center text-sm text-text">
						Layer {layer.index}
					</div>
					<label class="dark:text-text-dark text-xs text-text">
						Bins
						<select
							value={layer.binCount}
							onchange={(event) => updateLayerCount(index, event.currentTarget.value)}
							disabled={loading || saving}
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark mt-1 w-full border border-border bg-surface px-2 py-1.5 text-sm text-text"
						>
							{#each allowedCounts as count}
								<option value={String(count)}>{count}</option>
							{/each}
						</select>
					</label>
				</div>
			{/each}
		</div>
	{/if}

	<div class="flex flex-wrap items-center gap-2">
		<button
			onclick={saveSettings}
			disabled={loading || saving || layers.length === 0}
			class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
		>
			{saving ? 'Saving...' : 'Save Storage Layer Settings'}
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
