<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';

	type ProviderInfo = {
		id: string;
		label: string;
		description: string;
	};

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

<svelte:head><title>Sorter - Classification Providers</title></svelte:head>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Classification Providers</div>
		<div class="mt-1 text-sm text-text-muted">
			Which service identifies each piece's mold, and which predicts its color. The two run in
			parallel during classification; if a remote color provider is slow or unreachable the piece
			falls back to Brickognize's color. Changes apply to the next piece — no restart needed.
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved. Applies to the next classified piece.</Alert>
	{/if}

	{#if loading}
		<div class="text-sm text-text-muted">Loading…</div>
	{:else}
		<SectionCard
			title="Color prediction"
			description="Which service answers what color is this piece."
		>
			<div class="flex flex-wrap gap-2">
				{#each colorProviders as p}
					<Button
						variant={selectedColor === p.id ? 'primary' : 'secondary'}
						size="sm"
						onclick={() => (selectedColor = p.id)}
					>
						{p.label}{p.id === activeColor ? ' (current)' : ''}
					</Button>
				{/each}
			</div>
			{#if currentColor}
				<div class="mt-3 text-sm text-text-muted">{currentColor.description}</div>
			{/if}
		</SectionCard>

		<SectionCard
			title="Mold detection"
			description="Which service answers what part is this piece."
		>
			<div class="flex flex-wrap gap-2">
				{#each moldProviders as p}
					<Button
						variant={selectedMold === p.id ? 'primary' : 'secondary'}
						size="sm"
						onclick={() => (selectedMold = p.id)}
					>
						{p.label}{p.id === activeMold ? ' (current)' : ''}
					</Button>
				{/each}
			</div>
			{#if currentMold}
				<div class="mt-3 text-sm text-text-muted">{currentMold.description}</div>
			{/if}
		</SectionCard>

		<div class="flex gap-3">
			<Button variant="primary" onclick={save} loading={saving}>Save</Button>
			<Button variant="secondary" onclick={load} disabled={saving}>Reset to saved</Button>
		</div>
	{/if}
</div>
