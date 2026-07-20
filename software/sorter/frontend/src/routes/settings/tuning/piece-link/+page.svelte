<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Button, Alert } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';

	type InstalledLinkModel = {
		local_id: string;
		name: string | null;
		model_id: string | null;
		downloaded_at: string | null;
	};

	let enabled = $state(false);
	let algorithm = $state('');
	let installed = $state<InstalledLinkModel[]>([]);
	let metaFeatures = $state('');
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);
	// Whether we actually heard back. Without it a failed fetch would render the
	// "no model installed" hint, which we have no basis to claim.
	let loaded = $state(false);

	// Nothing to enable without a model on disk — the toggle would just fail
	// silently at the first piece.
	let hasModel = $derived(installed.length > 0);

	async function load() {
		loading = true;
		error = null;
		loaded = false;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/link-matching`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			enabled = Boolean(data.config?.enabled);
			algorithm = String(data.config?.algorithm ?? '');
			installed = data.installed ?? [];
			metaFeatures = String(data.meta_features ?? '');
			loaded = true;
		} catch (e: any) {
			error = e.message ?? 'Failed to load config';
		} finally {
			loading = false;
		}
	}

	async function save() {
		saving = true;
		error = null;
		saved = false;
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/link-matching`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled, algorithm })
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			enabled = Boolean(data.config?.enabled);
			algorithm = String(data.config?.algorithm ?? '');
			saved = true;
			setTimeout(() => (saved = false), 3000);
		} catch (e: any) {
			error = e.message ?? 'Failed to save config';
		} finally {
			saving = false;
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '—';
		const d = new Date(iso);
		return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
	}

	$effect(() => {
		load();
	});
</script>

<svelte:head><title>Sorter - Piece Link Matching</title></svelte:head>

<div class="flex flex-col gap-6 p-6">
	<div>
		<div class="flex flex-wrap items-center gap-2">
			<div class="text-lg font-semibold text-text">Piece Link Matching</div>
			<span
				class="bg-warning/20 px-2 py-0.5 text-xs font-semibold tracking-wider text-warning-dark uppercase dark:text-warning"
			>
				Experimental
			</span>
		</div>
		<div class="mt-1 text-sm text-text-muted">
			Given a piece that has just been classified at C4, score which of the upstream C2/C3 bbox
			crops are the same physical piece — from the crop images plus the timing and position data.
			Replaces the hand-tuned time/angle scoring on the piece detail page's "Possibly the same
			piece" gallery. Off by default; it costs one small CPU model pass per lookup.
		</div>
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if saved}
		<Alert variant="success">Saved.</Alert>
	{/if}

	{#if loading}
		<div class="text-sm text-text-muted">Loading…</div>
	{:else}
		{#if loaded && !hasModel}
			<Alert variant="info">
				No piece-link model is installed. Download one from
				<a class="underline" href="/settings/hive/models">Hive Models</a> — set the purpose filter
				to "Piece link" — then come back here to enable it.
			</Alert>
		{/if}

		{#if loaded}
		<SectionCard
			title="Matching"
			description="When enabled, the model re-ranks the candidates the time/angle lookup already found. It cannot find crops the lookup missed, so turning it off always falls back cleanly."
		>
			<label class="flex items-start gap-3">
				<input
					type="checkbox"
					bind:checked={enabled}
					disabled={!hasModel}
					class="mt-1 border border-border"
				/>
				<span class="flex flex-col">
					<span class="text-sm font-medium text-text">Use the model to rank possible crops</span>
					<span class="text-sm text-text-muted">
						{#if hasModel}
							The piece detail page will show a "Model" badge and each crop's match probability
							instead of the heuristic score.
						{:else}
							Unavailable until a piece-link model is installed.
						{/if}
					</span>
				</span>
			</label>
		</SectionCard>

		{#if hasModel}
			<SectionCard
				title="Model"
				description="Which installed piece-link model to use. Leave on Automatic unless you have more than one and want to pin a specific version."
			>
				<div class="flex flex-col gap-2">
					<label class="flex items-center gap-3 text-sm">
						<input type="radio" bind:group={algorithm} value="" />
						<span class="text-text">Automatic — use whichever is installed</span>
					</label>
					{#each installed as m (m.local_id)}
						<label class="flex items-start gap-3 text-sm">
							<input type="radio" bind:group={algorithm} value={m.local_id} class="mt-1" />
							<span class="flex flex-col">
								<span class="font-mono text-text">{m.name ?? m.local_id}</span>
								<span class="text-xs text-text-muted">
									downloaded {formatDate(m.downloaded_at)}
								</span>
							</span>
						</label>
					{/each}
				</div>
			</SectionCard>
		{/if}

		<div class="flex gap-3">
			<Button variant="primary" onclick={save} loading={saving} disabled={!hasModel && !enabled}>
				Save
			</Button>
			<Button variant="secondary" onclick={load} disabled={saving}>Reset to saved</Button>
		</div>

		{#if metaFeatures}
			<SectionCard
				title="Feature contract"
				description="The time/position features this build feeds the model, in order. A model trained on anything different refuses to load rather than scoring nonsense — if you see a mismatch error in the logs, the model and this software are out of sync."
			>
				<pre
					class="overflow-x-auto bg-bg p-3 text-xs text-text-muted">{metaFeatures}</pre>
			</SectionCard>
		{/if}
		{/if}
	{/if}
</div>
