<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import X from '@lucide/svelte/icons/x';

	type ModelOption = { id: string; label: string; description?: string };

	let {
		scope,
		camera,
		label,
		onClose
	}: {
		scope: 'feeder' | 'carousel';
		camera: 'c_channel_2' | 'c_channel_3' | 'carousel';
		label: string;
		onClose: () => void;
	} = $props();

	const manager = getMachinesContext();
	let algorithm = $state('');
	let models = $state<ModelOption[]>([]);
	let loading = $state(false);
	let saving = $state(false);
	let error_message = $state('');
	let status_message = $state('');
	let loaded_url = '';
	let request_sequence = 0;
	const config_url = $derived(
		(machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase()) +
			(scope === 'carousel'
				? '/api/carousel/detection-config'
				: `/api/feeder/detection-config?role=${encodeURIComponent(camera)}`)
	);

	async function loadConfig(url: string) {
		const sequence = ++request_sequence;
		loading = true;
		error_message = '';
		status_message = '';
		try {
			const response = await fetch(url);
			if (!response.ok) throw new Error(await response.text());
			const payload = await response.json();
			if (sequence !== request_sequence) return;
			algorithm = payload.algorithm ?? '';
			models = payload.available_algorithms ?? [];
		} catch (error) {
			if (sequence === request_sequence) error_message = String(error);
		} finally {
			if (sequence === request_sequence) loading = false;
		}
	}

	async function saveModel(value: string) {
		const url = config_url;
		if (!models.some((model) => model.id === value)) return;
		saving = true;
		error_message = '';
		status_message = '';
		try {
			const response = await fetch(url, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ algorithm: value })
			});
			if (!response.ok) throw new Error(await response.text());
			if (url !== config_url) return;
			algorithm = value;
			status_message = 'Detection model saved.';
		} catch (error) {
			if (url === config_url) error_message = String(error);
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		if (loaded_url === config_url) return;
		loaded_url = config_url;
		void loadConfig(config_url);
	});
</script>

<aside class="flex h-full min-w-0 flex-col border border-line bg-well">
	<div class="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
		<h3 class="text-sm font-semibold text-ink">{label} Detection</h3>
		<button onclick={onClose} aria-label="Close detection settings" class="p-2 text-ink-muted hover:text-ink">
			<X size={16} />
		</button>
	</div>
	<div class="flex flex-col gap-4 p-4">
		<label class="text-sm text-ink">
			Detection model
			<select
				value={algorithm}
				onchange={(event) => void saveModel(event.currentTarget.value)}
				disabled={loading || saving || models.length === 0}
				class="mt-2 w-full border border-line bg-surface px-2 py-2 text-sm text-ink"
			>
				{#if !models.some((model) => model.id === algorithm)}
					<option value={algorithm}>{algorithm || 'No model assigned'}</option>
				{/if}
				{#each models as model}
					<option value={model.id}>{model.label}</option>
				{/each}
			</select>
		</label>
		{#if !loading && models.length === 0}
			<p class="text-xs text-ink-muted">Install a detection model from Settings → Hive.</p>
		{/if}
		{#if error_message}<p class="text-sm text-danger-ink">{error_message}</p>{/if}
		{#if status_message}<p class="text-sm text-success-ink">{status_message}</p>{/if}
		<a href="/perception-debug" class="text-sm text-primary-ink underline">View live detection results</a>
	</div>
</aside>
