<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Input, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';

	type FieldMeta = {
		key: string;
		label: string;
		type: 'int' | 'float' | 'bool';
		default: number | boolean;
		section?: string;
	};

	let fields = $state<FieldMeta[]>([]);
	let values = $state<Record<string, number | boolean>>({});
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);

	// Group fields under their section, preserving first-seen section order.
	let sections = $derived.by(() => {
		const order: string[] = [];
		const bySection = new Map<string, FieldMeta[]>();
		for (const field of fields) {
			const section = field.section ?? 'Parameters';
			if (!bySection.has(section)) {
				bySection.set(section, []);
				order.push(section);
			}
			bySection.get(section)!.push(field);
		}
		return order.map((name) => ({ name, fields: bySection.get(name)! }));
	});

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception`);
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
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/feeder-pulse-perception`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(values),
			});
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
		<div class="text-lg font-semibold text-text">Feeder — Simple Pulse Tuning</div>
		<div class="mt-1 text-sm text-text-muted">
			Changes take effect within ~1 second (no restart needed).
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved. Changes apply within ~1 second.</Alert>
	{/if}

	<SectionCard title="Parameters" description="Pulse distance and pause time per region for the simple pulsing feeder.">
		{#if loading}
			<div class="text-sm text-text-muted">Loading…</div>
		{:else}
			<div class="flex flex-col gap-8">
				{#each sections as section}
					<div class="flex flex-col gap-4">
						<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
							{section.name}
						</div>
						{#each section.fields as field}
							<div class="flex items-center gap-4">
								<label class="w-72 text-sm text-text" for={field.key}>
									{field.label}
									<span class="ml-1 text-xs text-text-muted">(default: {field.default})</span>
								</label>
								{#if field.type === 'bool'}
									<input
										id={field.key}
										type="checkbox"
										checked={Boolean(values[field.key])}
										onchange={(e) => (values[field.key] = e.currentTarget.checked)}
									/>
								{:else}
									<div class="w-40">
										<Input id={field.key} type="number" bind:value={values[field.key]} />
									</div>
								{/if}
							</div>
						{/each}
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
