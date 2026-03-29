<script lang="ts">
	import type { components } from '$lib/api/rest';
	import { backendHttpBaseUrl } from '$lib/backend';
	import { onMount } from 'svelte';

	type RuntimeVariableDef = components['schemas']['RuntimeVariableDef'];

	let definitions: Record<string, RuntimeVariableDef> = $state({});
	let values: Record<string, number> = $state({});
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function getErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string' && data.detail.length > 0) {
				return data.detail;
			}
		} catch {
			// Fall back to the HTTP status if the response is not JSON.
		}
		return `HTTP ${res.status}`;
	}

	async function fetchVariables() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/runtime-variables`);
			if (!res.ok) throw new Error(await getErrorMessage(res));
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
			if (!res.ok) throw new Error(await getErrorMessage(res));
			const data = await res.json();
			values = data.values;
		} catch (e) {
			console.error('Failed to save runtime variables:', e);
			error = `Failed to save: ${e}`;
		} finally {
			loading = false;
		}
	}

	function formatLabel(key: string): string {
		return key.replace(/_/g, ' ');
	}

	onMount(() => {
		fetchVariables();
	});
</script>

{#if loading}
	<div class="dark:text-text-muted-dark py-8 text-center text-text-muted">Loading...</div>
{:else if error}
	<div class="py-8 text-center text-red-500">{error}</div>
{:else if Object.keys(definitions).length === 0}
	<div class="dark:text-text-muted-dark py-8 text-center text-text-muted">
		No runtime variables are exposed by the current backend.
	</div>
{:else}
	<div class="flex flex-col gap-3">
		{#each Object.entries(definitions) as [key, def]}
			<div class="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
				<label for={`runtime-var-${key}`} class="dark:text-text-dark text-sm text-text capitalize">
					{formatLabel(key)}
					{#if def.unit}
						<span class="dark:text-text-muted-dark text-text-muted">({def.unit})</span>
					{/if}
				</label>
				<input
					id={`runtime-var-${key}`}
					type="text"
					bind:value={values[key]}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark w-full border border-border bg-bg px-2 py-1 text-right text-sm text-text sm:w-24"
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
