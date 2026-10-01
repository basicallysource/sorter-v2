<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import X from '@lucide/svelte/icons/x';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';

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
	const modelOptions = $derived([
		...(models.some((model) => model.id === algorithm)
			? []
			: [{ value: algorithm, label: algorithm || 'No model assigned' }]),
		...models.map((model) => ({ value: model.id, label: model.label }))
	]);
</script>

<Panel title="Detection" description="The model that finds pieces on {label}.">
	{#snippet actions()}
		<Button variant="ghost" size="sm" icon={X} label="Close the detection settings" onclick={onClose} />
	{/snippet}
	<div class="flex flex-col gap-4 text-sm">
		<Field
			label="Detection model"
			for="detection-model"
			help={!loading && models.length === 0 ? 'Install a detection model from Settings > Hive.' : undefined}
		>
			<Select
				id="detection-model"
				value={algorithm}
				options={modelOptions}
				disabled={loading || saving || models.length === 0}
				onchange={(id) => void saveModel(id)}
			/>
		</Field>
		{#if error_message}<p class="text-danger-ink">{error_message}</p>{/if}
		{#if status_message}<p class="text-success-ink">{status_message}</p>{/if}
		<a href="/perception-debug" class="font-medium text-primary-ink hover:underline">
			See the live detection results
		</a>
	</div>
</Panel>
