<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type SwatchModel } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';

	let models = $state<SwatchModel[]>([]);
	let modelDir = $state('');
	let sourceRoles = $state<string[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let busyId = $state<string | null>(null);

	const activeModel = $derived(models.find((m) => m.is_active) ?? null);

	$effect(() => {
		if (!auth.initialized) return;
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
	});

	function message(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : fallback;
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await api.listSwatchModels();
			models = res.models;
			modelDir = res.model_dir;
			sourceRoles = res.source_roles;
		} catch (e: unknown) {
			error = message(e, 'Failed to load swatch models');
		} finally {
			loading = false;
		}
	}

	async function setActive(model: SwatchModel, active: boolean) {
		if (busyId) return;
		busyId = model.id;
		error = null;
		try {
			if (active) await api.activateSwatchModel(model.id);
			else await api.deactivateSwatchModel(model.id);
			models = models.map((m) => ({ ...m, is_active: active && m.id === model.id }));
		} catch (e: unknown) {
			error = message(e, active ? 'Failed to activate model' : 'Failed to deactivate model');
		} finally {
			busyId = null;
		}
	}

	function fmtSize(bytes: number): string {
		if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
		return `${bytes} B`;
	}
</script>

<svelte:head>
	<title>Swatch models - Hive</title>
</svelte:head>

<PageHeader
	title="Swatch models"
	description="A swatch model finds the colour reference palette's tiles in a classification-camera frame and reads each one's colour. While one is active, every new frame from that camera is read in the background. A model is an ONNX file in the scan folder on the server; this page shows what is there."
>
	{#snippet actions()}
		<Button href="/admin/jobs" variant="ghost" icon={ArrowRight}>Background jobs</Button>
		<Button icon={RefreshCw} onclick={load} {loading}>Rescan</Button>
	{/snippet}
</PageHeader>

<div class="flex flex-col gap-(--gap-panels)">
	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size={32} /></div>
	{:else if models.length === 0}
		<Panel>
			<EmptyState title="No models in the scan folder">Put a swatch finder's <code class="font-mono">.onnx</code> file in the scan folder and rescan.</EmptyState>
		</Panel>
	{:else}
		<Panel
			title={`${models.length} model${models.length === 1 ? '' : 's'} on disk`}
			description={activeModel
				? `Active: ${activeModel.name}. Only one is active at a time.`
				: 'None is active, so no frames are read.'}
			flush
		>
			<ul class="divide-y divide-line border-t border-line">
				{#each models as m (m.id)}
					<li class="flex flex-wrap items-center gap-4 px-(--pad-panel) py-3 {m.is_active ? 'bg-primary-soft' : ''}">
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-center gap-2">
								<span class="font-medium text-ink">{m.name}</span>
								{#if m.is_active}<Badge tone="primary">Active</Badge>{/if}
							</div>
							{#if m.description}<p class="mt-0.5 truncate text-sm text-ink-muted">{m.description}</p>{/if}
							<p class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-sm break-all text-ink-muted">
								<span class="font-mono">{m.filename}</span>
								<span class="num">{m.colour_count} colours</span>
								{#if m.net_long_side}<span class="num">runs at {m.net_long_side} px</span>{/if}
								<span class="num">{fmtSize(m.file_size)}</span>
								<span class="font-mono" title={m.sha256}>sha {m.sha256.slice(0, 10)}</span>
							</p>
						</div>
						{#if m.is_active}
							<Button size="sm" loading={busyId === m.id} onclick={() => setActive(m, false)}>Deactivate</Button>
						{:else}
							<Button variant="primary" size="sm" loading={busyId === m.id} onclick={() => setActive(m, true)}>Activate</Button>
						{/if}
					</li>
				{/each}
			</ul>
		</Panel>
	{/if}

	{#if modelDir}
		<p class="text-sm text-ink-muted">
			Scan folder <code class="rounded-control bg-surface px-1.5 py-0.5 font-mono break-all text-ink">{modelDir}</code>.
			Frames read: samples whose source is {sourceRoles.join(' or ') || 'none'}.
		</p>
	{/if}
</div>
