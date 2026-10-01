<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import SettingsSaveBar from '$lib/components/settings/SettingsSaveBar.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ProviderSelect from '$lib/components/settings/ProviderSelect.svelte';
	import type { ProviderInfo } from '$lib/components/settings/ProviderSelect.svelte';

	let colorProviders = $state<ProviderInfo[]>([]);
	let moldProviders = $state<ProviderInfo[]>([]);
	let activeColor = $state('');
	let activeMold = $state('');
	let selectedColor = $state('');
	let selectedMold = $state('');
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);

	let currentColor = $derived(colorProviders.find((p) => p.id === selectedColor));
	let currentMold = $derived(moldProviders.find((p) => p.id === selectedMold));

	function applyData(data: any) {
		colorProviders = data.color_providers ?? [];
		moldProviders = data.mold_providers ?? [];
		activeColor = data.active?.color_provider ?? '';
		activeMold = data.active?.mold_provider ?? '';
		selectedColor = activeColor;
		selectedMold = activeMold;
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/classification-providers`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			applyData(await res.json());
		} catch (e: any) {
			error = e.message ?? 'Failed to load providers';
		} finally {
			loading = false;
		}
	}

	async function save() {
		saving = true;
		saved = false;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/classification-providers`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					color_provider: selectedColor,
					mold_provider: selectedMold
				})
			});
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			applyData(await res.json());
			saved = true;
			setTimeout(() => (saved = false), 3000);
		} catch (e: any) {
			error = e.message ?? 'Failed to save providers';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		load();
	});
</script>

<svelte:head><title>Sorter - Providers</title></svelte:head>

<PageHeader
	title="Providers"
	description="Which service identifies each piece's mold, and which predicts its color. The two run side by side during classification; if a remote color provider is slow or unreachable, the piece falls back to Brickognize's color. Changes apply to the next piece, with no restart."
/>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}
{#if saved}
	<Alert tone="success">Saved. It applies to the next classified piece.</Alert>
{/if}

{#if loading}
	<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</div>
{:else}
	<Panel title="Color prediction" description="Which service says what color a piece is.">
		<ProviderSelect
			name="Color provider"
			options={colorProviders}
			bind:selected={selectedColor}
			active={activeColor}
		/>
	</Panel>

	<Panel title="Mold detection" description="Which service says what part a piece is.">
		<ProviderSelect
			name="Mold provider"
			options={moldProviders}
			bind:selected={selectedMold}
			active={activeMold}
		/>
	</Panel>

	<SettingsSaveBar {save} reset={load} {saving} />
{/if}
