<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import X from '@lucide/svelte/icons/x';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';

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
	// What the model boxes that is always in view, learned while the channel is
	// empty and dropped (backend perception/scenery.py).
	type SceneryStatus = {
		channel: number;
		enabled: boolean;
		learning: boolean;
		fixed: number;
		at_rest: number;
		dropped: number;
	};
	const SCENERY_CHANNEL: Record<'c_channel_2' | 'c_channel_3' | 'carousel', number> = {
		c_channel_2: 2,
		c_channel_3: 3,
		carousel: 4
	};
	const base = $derived(machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase());
	let scenery = $state<SceneryStatus | null>(null);
	let scenery_message = $state('');
	let scenery_busy = $state(false);

	async function loadScenery(url: string, channel: number) {
		try {
			const response = await fetch(`${url}/api/perception/scenery`);
			if (!response.ok) return;
			const payload = await response.json();
			scenery =
				(payload.channels ?? []).find((status: SceneryStatus) => status.channel === channel) ?? null;
		} catch {
			// Shown as not loaded.
		}
	}

	async function sceneryAction(action: string, body?: unknown, message = '') {
		scenery_busy = true;
		scenery_message = '';
		try {
			const response = await fetch(
				`${base}/api/perception/scenery/${SCENERY_CHANNEL[camera]}/${action}`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: body === undefined ? undefined : JSON.stringify(body)
				}
			);
			if (!response.ok) throw new Error(await response.text());
			scenery = await response.json();
			scenery_message = message;
		} catch (error) {
			scenery_message = String(error);
		} finally {
			scenery_busy = false;
		}
	}

	$effect(() => {
		const url = base;
		const channel = SCENERY_CHANNEL[camera];
		void loadScenery(url, channel);
		const timer = setInterval(() => void loadScenery(url, channel), 3000);
		return () => clearInterval(timer);
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
		<div class="flex flex-col gap-2 border-t border-line pt-4">
			<div class="flex items-center justify-between gap-3">
				<p class="font-medium text-ink">Ignore what is always in view</p>
				<Switch
					label="Ignore what is always in view"
					checked={scenery?.enabled ?? true}
					disabled={!scenery || scenery_busy}
					onchange={(on) => void sceneryAction('enabled', { enabled: on })}
				/>
			</div>
			<p class="text-ink-muted">
				Boxes the model draws on what never changes, like a wall or a thread{camera === 'carousel'
					? ", and the rotor's fins while it rests"
					: ''}, are learned while the channel is empty and then dropped. The live view shows them grey.
			</p>
			{#if scenery}
				<p class="text-ink-muted">
					{scenery.learning
						? 'Learning now. Keep the channel empty.'
						: `${scenery.fixed + scenery.at_rest} learned${camera === 'carousel' ? ` (${scenery.at_rest} on the rotor at rest)` : ''}, ${scenery.dropped} dropped since the last start.`}
				</p>
			{/if}
			<div class="flex flex-wrap gap-2">
				<Button
					size="sm"
					disabled={scenery_busy || !scenery || scenery.learning}
					onclick={() => void sceneryAction('learn', undefined, 'Learning for a few seconds. Keep the channel empty.')}
				>
					Learn the empty scene
				</Button>
				<Button
					size="sm"
					variant="ghost"
					disabled={scenery_busy || !scenery || scenery.fixed + scenery.at_rest === 0}
					onclick={() => void sceneryAction('forget', undefined, 'Forgotten.')}
				>
					Forget
				</Button>
			</div>
			{#if scenery_message}<p class="text-ink-muted">{scenery_message}</p>{/if}
		</div>
		<a href="/perception-debug" class="font-medium text-primary-ink hover:underline">
			See the live detection results
		</a>
	</div>
</Panel>
