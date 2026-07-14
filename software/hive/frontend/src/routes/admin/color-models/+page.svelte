<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type ColorModel } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Alert, Button } from '$lib/components/primitives';

	let models = $state<ColorModel[]>([]);
	let modelDir = $state('');
	let loading = $state(true);
	let error = $state<string | null>(null);
	let busyId = $state<string | null>(null);

	const activeModel = $derived(models.find((m) => m.is_active) ?? null);

	$effect(() => {
		// Wait for auth to initialize so a direct load / refresh of this URL
		// doesn't bounce an admin out before their session is known.
		if (!auth.initialized) return;
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		void load();
	});

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await api.listColorModels();
			models = res.models;
			modelDir = res.model_dir;
		} catch (e: unknown) {
			error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to load color models';
		} finally {
			loading = false;
		}
	}

	async function activate(model: ColorModel) {
		if (busyId) return;
		busyId = model.id;
		error = null;
		try {
			await api.activateColorModel(model.id);
			models = models.map((m) => ({ ...m, is_active: m.id === model.id }));
		} catch (e: unknown) {
			error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to activate model';
		} finally {
			busyId = null;
		}
	}

	async function deactivate(model: ColorModel) {
		if (busyId) return;
		busyId = model.id;
		error = null;
		try {
			await api.deactivateColorModel(model.id);
			models = models.map((m) => ({ ...m, is_active: false }));
		} catch (e: unknown) {
			error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to deactivate model';
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
	<title>Color Models · Hive</title>
</svelte:head>

<div class="space-y-5">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 class="text-2xl font-bold text-text">Color models</h1>
			<p class="mt-1 max-w-2xl text-sm text-text-muted">
				The active model predicts a piece's color from its crops in the labeling view, alongside the
				pixel-average guess. Models are ONNX files uploaded to the scan directory on the server; this
				page reflects whatever is on disk.
			</p>
		</div>
		<Button variant="secondary" size="sm" onclick={load} loading={loading}>Rescan</Button>
	</div>

	{#if modelDir}
		<p class="text-xs text-text-muted">
			Scan directory: <code class="bg-bg px-1.5 py-0.5 text-text">{modelDir}</code>
		</p>
	{/if}

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	{#if loading}
		<div class="flex justify-center py-16"><Spinner /></div>
	{:else if models.length === 0}
		<div class="border border-border bg-surface px-4 py-10 text-center text-sm text-text-muted">
			No color models found in the scan directory. Upload an <code>.onnx</code> file there and hit Rescan.
		</div>
	{:else}
		<div class="border border-border bg-surface">
			<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-2">
				<span class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
					{models.length} model{models.length === 1 ? '' : 's'} on disk
				</span>
				<span class="text-xs text-text-muted">
					{#if activeModel}
						Active: <span class="font-medium text-text">{activeModel.name}</span>
					{:else}
						None active — using pixel-average guess
					{/if}
				</span>
			</div>

			{#each models as m (m.id)}
				<div class="flex flex-wrap items-center gap-4 border-b border-border px-4 py-3 last:border-b-0 {m.is_active ? 'bg-primary-light/30' : ''}">
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<span class="font-medium text-text">{m.name}</span>
							{#if m.is_active}
								<span class="border border-primary/30 bg-primary-light px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">Active</span>
							{/if}
						</div>
						{#if m.description}
							<p class="mt-0.5 truncate text-xs text-text-muted">{m.description}</p>
						{/if}
						<p class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
							<span><code class="text-text-muted">{m.filename}</code></span>
							<span>{m.class_count} colors</span>
							<span>{m.input_size}×{m.input_size}</span>
							<span>{fmtSize(m.file_size)}</span>
							<span title={m.sha256}>sha {m.sha256.slice(0, 10)}</span>
						</p>
					</div>
					<div class="flex items-center gap-2">
						{#if m.is_active}
							<Button variant="secondary" size="sm" loading={busyId === m.id} onclick={() => deactivate(m)}>
								Deactivate
							</Button>
						{:else}
							<Button variant="primary" size="sm" loading={busyId === m.id} onclick={() => activate(m)}>
								Activate
							</Button>
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<p class="text-xs text-text-muted">
			Only one model is active at a time. Deactivating leaves the labeling view on the pixel-average
			guess.
		</p>
	{/if}
</div>
