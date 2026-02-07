<script lang="ts">
	import Modal from './Modal.svelte';
	import type { components } from '$lib/api/rest';
	import { backendHttpBaseUrl } from '$lib/backend';

	type RuntimeVariableDef = components['schemas']['RuntimeVariableDef'];

	let { open = $bindable(false) } = $props();

	let definitions: Record<string, RuntimeVariableDef> = $state({});
	let values: Record<string, number> = $state({});
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function fetchVariables() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/runtime-variables`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			definitions = data.definitions;
			values = data.values;
		} catch (e) {
			console.error('Failed to load runtime variables:', e);
			error = `Failed to load: ${e}`;
		} finally {
			loading = false;
		}
	}

	async function saveVariables() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/runtime-variables`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ values })
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			values = data.values;
		} catch (e) {
			console.error('Failed to save runtime variables:', e);
			error = `Failed to save: ${e}`;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (open) {
			fetchVariables();
		}
	});

	function formatLabel(key: string): string {
		return key.replace(/_/g, ' ');
	}
</script>

<Modal bind:open title="Runtime Variables">
	{#if loading}
		<div class="dark:text-text-muted-dark py-8 text-center text-text-muted">Loading...</div>
	{:else if error}
		<div class="py-8 text-center text-red-500">{error}</div>
	{:else}
		<div class="flex flex-col gap-3">
			{#each Object.entries(definitions) as [key, def]}
				<div class="flex items-center justify-between gap-4">
					<label class="dark:text-text-dark text-sm text-text capitalize">
						{formatLabel(key)}
						{#if def.unit}
							<span class="dark:text-text-muted-dark text-text-muted">({def.unit})</span>
						{/if}
					</label>
					<input
						type="text"
						bind:value={values[key]}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-24 border border-border bg-bg px-2 py-1 text-right text-sm text-text"
					/>
				</div>
			{/each}
		</div>
		<div class="mt-6 flex justify-end">
			<button
				onclick={saveVariables}
				disabled={loading}
				class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-4 py-2 text-sm text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
			>
				Apply Changes
			</button>
		</div>
	{/if}
</Modal>
