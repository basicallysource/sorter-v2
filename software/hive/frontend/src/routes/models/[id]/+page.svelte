<script lang="ts">
	import { page } from '$app/state';
	import { api, type DetectionModelDetail } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	let model = $state<DetectionModelDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		const id = page.params.id;
		if (!id) return;
		void load(id);
	});

	async function load(id: string) {
		loading = true;
		error = null;
		try {
			model = await api.getModel(id);
		} catch (err: unknown) {
			const apiErr = err as { error?: string };
			error = apiErr?.error || 'Failed to load model';
		} finally {
			loading = false;
		}
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	function downloadUrl(variantId: string): string {
		return model ? api.modelVariantDownloadUrl(model.id, variantId) : '#';
	}
</script>

<div class="space-y-6">
	<a href="/models" class="text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← Back to models</a>

	{#if loading}
		<div class="flex justify-center py-12"><Spinner /></div>
	{:else if error}
		<div class="border border-primary bg-primary-light p-3 text-sm text-primary">{error}</div>
	{:else if model}
		<header>
			<h1 class="text-2xl font-bold text-[var(--color-text)]">{model.name}</h1>
			<p class="font-mono text-sm text-[var(--color-text-muted)]">
				{model.slug} · v{model.version} · {model.model_family}
			</p>
			{#if model.description}
				<p class="mt-2 text-sm text-[var(--color-text)]">{model.description}</p>
			{/if}
			<div class="mt-3 flex flex-wrap gap-2">
				{#each (model.scopes ?? []) as scope (scope)}
					<span class="border border-[var(--color-border)] px-2 py-0.5 text-xs text-[var(--color-text-muted)]">{scope}</span>
				{/each}
				{#if !model.is_public}
					<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-0.5 text-xs text-[var(--color-text-muted)]">Private</span>
				{/if}
			</div>
		</header>

		<section>
			<h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Variants</h2>
			<div class="border border-[var(--color-border)] bg-[var(--color-surface)]">
				<table class="w-full text-sm">
					<thead class="border-b border-[var(--color-border)] bg-[var(--color-bg)] text-left text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
						<tr>
							<th class="px-3 py-2">Runtime</th>
							<th class="px-3 py-2">File</th>
							<th class="px-3 py-2">Size</th>
							<th class="px-3 py-2">SHA-256</th>
							<th class="px-3 py-2 text-right"></th>
						</tr>
					</thead>
					<tbody>
						{#each model.variants as variant (variant.id)}
							<tr class="border-b border-[var(--color-border)] last:border-b-0">
								<td class="px-3 py-2 font-mono text-xs">{variant.runtime}</td>
								<td class="px-3 py-2 font-mono text-xs">{variant.file_name}</td>
								<td class="px-3 py-2">{formatSize(variant.file_size)}</td>
								<td class="px-3 py-2 font-mono text-xs text-[var(--color-text-muted)]">{variant.sha256.slice(0, 16)}…</td>
								<td class="px-3 py-2 text-right">
									<a
										href={downloadUrl(variant.id)}
										class="bg-primary px-3 py-1 text-xs font-medium text-white hover:bg-primary-hover"
										download={variant.file_name}
									>
										Download
									</a>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		{#if model.training_metadata}
			<section>
				<h2 class="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Training metadata</h2>
				<pre class="max-h-96 overflow-auto border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-xs text-[var(--color-text)]">{JSON.stringify(model.training_metadata, null, 2)}</pre>
			</section>
		{/if}
	{/if}
</div>
