<script lang="ts">
	import { page } from '$app/state';
	import { api, type DetectionModelDetail, type DetectionModelVariant } from '$lib/api';
	import ModelTrainingReport from '$lib/components/ModelTrainingReport.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let model = $state<DetectionModelDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let downloadsOpen = $state(false);

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

	function formatDate(value: string | undefined): string {
		if (!value) return '—';
		return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	}

	const runtimeAccent: Record<string, string> = {
		onnx: 'var(--color-info)',
		ncnn: 'var(--color-success)',
		pytorch: 'var(--color-primary)',
		tflite: 'var(--color-warning)'
	};

	function variantAccent(variant: DetectionModelVariant): string {
		return runtimeAccent[variant.runtime.toLowerCase()] ?? 'var(--color-text-muted)';
	}
</script>

<svelte:window onclick={() => { downloadsOpen = false; }} />

<div class="space-y-6">
	<a href="/models" class="inline-flex items-center gap-1 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]">← Back to models</a>

	{#if loading}
		<div class="flex justify-center py-12"><Spinner /></div>
	{:else if error}
		<div class="border border-primary bg-primary-light p-3 text-sm text-primary">{error}</div>
	{:else if model}
		<header class="relative border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3">
			<div class="absolute inset-y-0 left-0 w-0.5 bg-primary"></div>
			<div class="flex flex-wrap items-start justify-between gap-3 pl-2">
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] uppercase tracking-wider text-[var(--color-text-muted)]">
						<span class="font-mono text-[var(--color-text)]">{model.slug}</span>
						<span>v{model.version}</span>
						<span>·</span>
						<span>{model.model_family}</span>
						{#if !model.is_public}
							<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-1.5 py-0.5">Private</span>
						{/if}
						<span>· published {formatDate(model.published_at)}</span>
					</div>
					<h1 class="mt-1 text-xl font-semibold tracking-tight text-[var(--color-text)]">{model.name}</h1>
					{#if model.description}
						<p class="mt-1 max-w-3xl text-sm text-[var(--color-text-muted)]">{model.description}</p>
					{/if}
					{#if model.scopes && model.scopes.length > 0}
						<div class="mt-2 flex flex-wrap gap-1">
							{#each model.scopes as scope (scope)}
								<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--color-text)]">{scope}</span>
							{/each}
						</div>
					{/if}
				</div>

				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
				<div class="relative shrink-0" onclick={(event) => event.stopPropagation()}>
					<button
						type="button"
						onclick={() => { downloadsOpen = !downloadsOpen; }}
						class="inline-flex items-center gap-2 border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm font-medium text-[var(--color-text)] hover:border-primary hover:text-primary"
					>
						<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
							<path d="M10 3a.75.75 0 01.75.75v7.69l2.22-2.22a.75.75 0 111.06 1.06l-3.5 3.5a.75.75 0 01-1.06 0l-3.5-3.5a.75.75 0 111.06-1.06l2.22 2.22V3.75A.75.75 0 0110 3z" />
							<path d="M3.5 14a.75.75 0 01.75.75v.75c0 .138.112.25.25.25h11a.25.25 0 00.25-.25v-.75a.75.75 0 011.5 0v.75A1.75 1.75 0 0115.5 17h-11A1.75 1.75 0 012.75 15.25v-.75A.75.75 0 013.5 14z" />
						</svg>
						Download
						<span class="rounded-none bg-[var(--color-bg)] px-1.5 text-[11px] tabular-nums text-[var(--color-text-muted)]">{model.variants.length}</span>
						<svg class="h-3 w-3 transition-transform {downloadsOpen ? 'rotate-180' : ''}" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
							<path fill-rule="evenodd" d="M5.22 7.22a.75.75 0 011.06 0L10 10.94l3.72-3.72a.75.75 0 111.06 1.06l-4.25 4.25a.75.75 0 01-1.06 0L5.22 8.28a.75.75 0 010-1.06z" clip-rule="evenodd" />
						</svg>
					</button>
					{#if downloadsOpen}
						<div class="absolute right-0 z-10 mt-1 w-80 border border-[var(--color-border)] bg-[var(--color-surface)] shadow-lg">
							<div class="border-b border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5 text-[11px] uppercase tracking-wider text-[var(--color-text-muted)]">
								Model variants
							</div>
							{#each model.variants as variant (variant.id)}
								<a
									href={downloadUrl(variant.id)}
									download={variant.file_name}
									class="relative flex items-center gap-3 border-b border-[var(--color-border)] px-3 py-2 last:border-b-0 hover:bg-[var(--color-bg)]"
									onclick={() => { downloadsOpen = false; }}
								>
									<span class="h-8 w-0.5 shrink-0" style={`background: ${variantAccent(variant)};`}></span>
									<div class="min-w-0 flex-1">
										<div class="flex items-baseline justify-between gap-2">
											<span class="font-mono text-xs uppercase tracking-wider" style={`color: ${variantAccent(variant)};`}>{variant.runtime}</span>
											<span class="text-xs tabular-nums text-[var(--color-text-muted)]">{formatSize(variant.file_size)}</span>
										</div>
										<div class="mt-0.5 truncate font-mono text-xs text-[var(--color-text)]" title={variant.file_name}>{variant.file_name}</div>
										<div class="mt-0.5 font-mono text-[10px] text-[var(--color-text-muted)]" title={variant.sha256}>sha256 {variant.sha256.slice(0, 16)}…</div>
									</div>
									<svg class="h-4 w-4 shrink-0 text-[var(--color-text-muted)]" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
										<path d="M10 3a.75.75 0 01.75.75v7.69l2.22-2.22a.75.75 0 111.06 1.06l-3.5 3.5a.75.75 0 01-1.06 0l-3.5-3.5a.75.75 0 111.06-1.06l2.22 2.22V3.75A.75.75 0 0110 3z" />
										<path d="M3.5 14a.75.75 0 01.75.75v.75c0 .138.112.25.25.25h11a.25.25 0 00.25-.25v-.75a.75.75 0 011.5 0v.75A1.75 1.75 0 0115.5 17h-11A1.75 1.75 0 012.75 15.25v-.75A.75.75 0 013.5 14z" />
									</svg>
								</a>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		</header>

		{#if model.training_metadata}
			<ModelTrainingReport metadata={model.training_metadata} />
		{/if}
	{/if}
</div>
