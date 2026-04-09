<script lang="ts">
	import type { Snippet } from 'svelte';
	import { createEventDispatcher } from 'svelte';
	import { RefreshCcw } from 'lucide-svelte';

	let {
		title = '',
		description = '',
		rootClass = '',
		headerClass = '',
		bodyClass = '',
		headerActions = null,
		children
	}: {
		title?: string;
		description?: string;
		rootClass?: string;
		headerClass?: string;
		bodyClass?: string;
		headerActions?: Snippet | null;
		children: Snippet;
	} = $props();

	const dispatch = createEventDispatcher<{ 'refresh-cameras': void }>();
</script>

<section class={`overflow-hidden border border-border ${rootClass}`.trim()}>
	{#if title}
		<div class={`border-b border-border bg-surface px-4 py-3 ${headerClass}`.trim()}>
			<div class="flex items-start justify-between gap-3">
				<div class="min-w-0 flex-1">
					<h2 class="text-base font-semibold text-text">{title}</h2>
					{#if description}
						<p class="mt-1 text-sm text-text-muted">{description}</p>
					{/if}
				</div>
				{#if headerActions}
					<div class="shrink-0">
						{@render headerActions()}
					</div>
				{:else if title === 'Cameras'}
					<button
						type="button"
						class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors"
						title="Refresh camera sources"
						onclick={() => dispatch('refresh-cameras')}
					>
						<RefreshCcw size={14} />
					</button>
				{/if}
			</div>
		</div>
	{/if}
	<div class={`p-4 ${bodyClass}`.trim()}>
		{@render children()}
	</div>
</section>
