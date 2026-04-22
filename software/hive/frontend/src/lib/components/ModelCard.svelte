<script lang="ts">
	import type { DetectionModelSummary } from '$lib/api';

	interface Props {
		model: DetectionModelSummary;
	}

	let { model }: Props = $props();

	function formatDate(value: string): string {
		return new Date(value).toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	}
</script>

<a
	href="/models/{model.id}"
	class="block border border-[var(--color-border)] bg-[var(--color-surface)] p-4 hover:border-primary"
>
	<div class="mb-2 flex items-start justify-between gap-4">
		<div>
			<h3 class="text-base font-semibold text-[var(--color-text)]">{model.name}</h3>
			<p class="font-mono text-xs text-[var(--color-text-muted)]">{model.slug} · v{model.version}</p>
		</div>
		{#if !model.is_public}
			<span class="border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-0.5 text-xs text-[var(--color-text-muted)]">Private</span>
		{/if}
	</div>

	{#if model.description}
		<p class="mb-3 text-sm text-[var(--color-text-muted)]">{model.description}</p>
	{/if}

	<div class="flex flex-wrap items-center gap-2">
		<span class="bg-[var(--color-bg)] px-2 py-0.5 text-xs text-[var(--color-text)]">
			{model.model_family}
		</span>
		{#each model.variant_runtimes as runtime (runtime)}
			<span class="bg-info px-2 py-0.5 text-xs text-white">{runtime}</span>
		{/each}
		{#each (model.scopes ?? []) as scope (scope)}
			<span class="border border-[var(--color-border)] px-2 py-0.5 text-xs text-[var(--color-text-muted)]">{scope}</span>
		{/each}
	</div>

	<p class="mt-3 text-xs text-[var(--color-text-muted)]">Published {formatDate(model.published_at)}</p>
</a>
