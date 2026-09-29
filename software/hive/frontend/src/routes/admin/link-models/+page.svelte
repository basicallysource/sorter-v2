<script lang="ts">
	import { auth } from '$lib/auth.svelte';
	import { api, type LinkModel } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';

	let models = $state<LinkModel[]>([]);
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
			const res = await api.listLinkModels();
			models = res.models;
			modelDir = res.model_dir;
		} catch (e: unknown) {
			error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to load link models';
		} finally {
			loading = false;
		}
	}

	async function activate(model: LinkModel) {
		if (busyId) return;
		busyId = model.id;
		error = null;
		try {
			await api.activateLinkModel(model.id);
			models = models.map((m) => ({ ...m, is_active: m.id === model.id }));
		} catch (e: unknown) {
			error = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to activate model';
		} finally {
			busyId = null;
		}
	}

	async function deactivate(model: LinkModel) {
		if (busyId) return;
		busyId = model.id;
		error = null;
		try {
			await api.deactivateLinkModel(model.id);
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
	<title>Link Models · Hive</title>
</svelte:head>

<div class="space-y-5">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 class="text-2xl font-bold text-ink">Link models</h1>
			<p class="mt-1 max-w-2xl text-sm text-ink-muted">
				The active model scores which upstream C2/C3 crops are the same physical piece as a
				classified piece, and its picks pre-select the same-piece panel in the labeling view — in
				place of the time/angle heuristic. Each model is a pair of ONNX graphs
				(<code>*.encoder.onnx</code> + <code>*.head.onnx</code>) uploaded to the scan directory on
				the server; this page reflects whatever is on disk.
			</p>
		</div>
		<Button variant="secondary" size="sm" onclick={load} loading={loading}>Rescan</Button>
	</div>

	{#if modelDir}
		<p class="text-xs text-ink-muted">
			Scan directory: <code class="break-all bg-well px-1.5 py-0.5 text-ink">{modelDir}</code>
		</p>
	{/if}

	{#if error}
		<Alert tone="danger">{error}</Alert>
	{/if}

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size={32} /></div>
	{:else if models.length === 0}
		<div class="border border-line bg-surface px-4 py-10 text-center text-sm text-ink-muted">
			No link models found in the scan directory. Upload an encoder+head <code>.onnx</code> pair there
			and hit Rescan.
		</div>
	{:else}
		<div class="border border-line bg-surface">
			<div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line bg-well px-4 py-2">
				<span class="text-xs font-semibold uppercase tracking-wider text-ink-muted">
					{models.length} model{models.length === 1 ? '' : 's'} on disk
				</span>
				<span class="text-xs text-ink-muted">
					{#if activeModel}
						Active: <span class="font-medium text-ink">{activeModel.name}</span>
					{:else}
						None active — using time/angle heuristic
					{/if}
				</span>
			</div>

			{#each models as m (m.id)}
				<div class="flex flex-wrap items-center gap-4 border-b border-line px-4 py-3 last:border-b-0 {m.is_active ? 'bg-primary-soft' : ''}">
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<span class="font-medium text-ink">{m.name}</span>
							{#if m.is_active}
								<span class="border border-primary/30 bg-primary-soft px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-primary-ink">Active</span>
							{/if}
						</div>
						{#if m.description}
							<p class="mt-0.5 truncate text-xs text-ink-muted">{m.description}</p>
						{/if}
						<p class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 break-all text-xs text-ink-muted">
							<span><code class="text-ink-muted">{m.encoder_filename}</code> + <code class="text-ink-muted">{m.head_filename}</code></span>
							<span>{m.input_size}×{m.input_size}</span>
							<span>{m.embed_dim}-d embed</span>
							<span>{m.meta_dim} meta</span>
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

		<p class="text-xs text-ink-muted">
			Only one model is active at a time. Deactivating leaves the labeling view on the time/angle
			heuristic.
		</p>
	{/if}
</div>
