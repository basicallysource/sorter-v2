<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import SettingsSaveBar from '$lib/components/settings/SettingsSaveBar.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import RadioGroup from '$lib/components/ui/RadioGroup.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';

	type InstalledLinkModel = {
		local_id: string;
		name: string | null;
		model_id: string | null;
		downloaded_at: string | null;
	};

	let enabled = $state(false);
	let algorithm = $state('');
	let minConfidence = $state(0.95);
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
			minConfidence = Number(data.config?.min_confidence ?? 0.95);
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
			const min_confidence = Math.min(Math.max(Number(minConfidence) || 0, 0), 1);
			const res = await fetch(`${getBackendHttpBase()}/api/tuning/link-matching`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled, algorithm, min_confidence })
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			enabled = Boolean(data.config?.enabled);
			algorithm = String(data.config?.algorithm ?? '');
			minConfidence = Number(data.config?.min_confidence ?? 0.95);
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

<svelte:head><title>Sorter - Piece link matching</title></svelte:head>

<PageHeader
	title="Piece link matching"
	description="Given a piece just classified on C4, score which of the upstream C2 and C3 crops show the same piece, from the crop pictures and the timing and position data. It replaces the hand-tuned time and angle scoring in the piece page's &quot;Possibly the same piece&quot; gallery. Off by default: it costs one small CPU model pass per lookup."
>
	<Badge tone="warning">Experimental</Badge>
</PageHeader>

{#if error}
	<Alert tone="danger">{error}</Alert>
{/if}
{#if saved}
	<Alert tone="success">Saved.</Alert>
{/if}

{#if loading}
	<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</div>
{:else}
	{#if loaded && !hasModel}
		<Alert tone="info">
			No piece-link model is installed. Download one from
			<a class="font-medium underline" href="/settings/hive/models">Local models</a> (set the purpose
			to "Piece link"), then come back to turn it on.
		</Alert>
	{/if}

	{#if loaded}
		<Panel
			title="Matching"
			description="The model re-ranks the candidates the time and angle lookup already found. It can't find crops the lookup missed, so turning it off always falls back cleanly."
			flush
		>
			<div class="divide-y divide-line">
				<div class="px-(--pad-panel) py-(--pad-row)">
					<Checkbox bind:checked={enabled} disabled={!hasModel}>
						<span class="font-medium">Use the model to rank the possible crops</span>
					</Checkbox>
					<p class="mt-1 ml-6.5 text-sm text-ink-muted">
						{#if hasModel}
							The piece page then shows a "Model" badge and each crop's match probability instead of
							the heuristic score.
						{:else}
							Unavailable until a piece-link model is installed.
						{/if}
					</p>
				</div>
				<SettingRow
					label="Minimum confidence"
					help="Crops scoring at or above this (0 to 1) count as the same piece. Below it they still show on the piece page, unchecked and never fused into the classification. Overrides the cutoff built into the model (0.5 for link-v3)."
					for="link-min-confidence"
				>
					<Input
						id="link-min-confidence"
						type="number"
						bind:value={minConfidence}
						disabled={!hasModel}
						class="w-28"
					/>
				</SettingRow>
			</div>
		</Panel>

		{#if hasModel}
			<Panel
				title="Model"
				description="Which installed piece-link model to use. Leave it on automatic unless there is more than one and you want to pin a version."
			>
				<RadioGroup
					name="piece-link-model"
					label="Piece-link model"
					bind:value={algorithm}
					options={[
						{ value: '', label: 'Automatic', help: 'Use whichever one is installed.' },
						...installed.map((m) => ({
							value: m.local_id,
							label: m.name ?? m.local_id,
							help: `Downloaded ${formatDate(m.downloaded_at)}`
						}))
					]}
				/>
			</Panel>
		{/if}

		<SettingsSaveBar {save} reset={load} {saving} disabled={!hasModel && !enabled} />

		{#if metaFeatures}
			<Panel
				title="Feature contract"
				description="The time and position features this build feeds the model, in order. A model trained on anything different refuses to load rather than score nonsense: a mismatch error in the log means the model and this software are out of step."
			>
				<pre
					class="overflow-x-auto rounded-control bg-well p-3 font-mono text-sm text-ink-muted">{metaFeatures}</pre>
			</Panel>
		{/if}
	{/if}
{/if}
