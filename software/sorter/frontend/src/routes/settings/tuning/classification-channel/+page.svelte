<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';

	type FieldMeta = { key: string; label: string; type: 'int' | 'float'; default: number };

	let fields = $state<FieldMeta[]>([]);
	let values = $state<Record<string, number>>({});
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/classification-channel-rev01`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			fields = data.fields;
			values = { ...data.config };
		} catch (e: any) {
			error = e.message ?? 'Failed to load config';
		} finally {
			loading = false;
		}
	}

	async function save() {
		saving = true;
		saved = false;
		error = null;
		try {
			const res = await fetch(
				`${getBackendHttpBase()}/api/tuning/classification-channel-rev01`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(values),
				}
			);
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				throw new Error(body.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			values = { ...data.config };
			saved = true;
			setTimeout(() => (saved = false), 3000);
		} catch (e: any) {
			error = e.message ?? 'Failed to save config';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		load();
	});
</script>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="text-lg font-semibold text-text">Classification Channel — Rev01 Tuning</div>
		<div class="mt-1 text-sm text-text-muted">
			Changes take effect on the next piece (no restart needed).
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved. Changes will apply on the next piece.</Alert>
	{/if}

	<SectionCard title="Parameters" description="All tunable parameters for the rev01 state machine.">
		{#if loading}
			<div class="text-sm text-text-muted">Loading…</div>
		{:else}
			<div class="flex flex-col gap-4">
				{#each fields as field}
					<div class="flex items-center gap-4">
						<label class="w-64 text-sm text-text" for={field.key}>
							{field.label}
							<span class="ml-1 text-xs text-text-muted">(default: {field.default})</span>
						</label>
						<div class="w-40">
							<Input
								id={field.key}
								type="number"
								bind:value={values[field.key]}
							/>
						</div>
					</div>
				{/each}
			</div>

			<div class="mt-6 flex gap-3">
				<Button variant="primary" onclick={save} loading={saving}>Save</Button>
				<Button variant="secondary" onclick={load} disabled={saving}>Reset to saved</Button>
			</div>
		{/if}
	</SectionCard>
</div>
