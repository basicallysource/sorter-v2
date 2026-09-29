<script lang="ts">
	// A settings panel, drawn as the design system's Panel: the surface plane,
	// no outline, the title and its sentence over the body.
	import type { Snippet } from 'svelte';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import Button from '$lib/components/ui/Button.svelte';

	let {
		title = '',
		description = '',
		headerActions = null,
		onrefreshcameras,
		children
	}: {
		title?: string;
		description?: string;
		headerActions?: Snippet | null;
		// The setup wizard's Cameras step offers a refresh of the camera list.
		onrefreshcameras?: () => void;
		children: Snippet;
	} = $props();
</script>

<section class="rounded-panel bg-surface">
	{#if title}
		<header class="flex items-start justify-between gap-4 px-(--pad-panel) pt-4 pb-3">
			<div class="min-w-0 flex-1">
				<h2 class="text-base font-semibold text-ink">{title}</h2>
				{#if description}
					<p class="mt-0.5 text-sm text-ink-muted">{description}</p>
				{/if}
			</div>
			{#if headerActions}
				<div class="shrink-0">{@render headerActions()}</div>
			{:else if title === 'Cameras' && onrefreshcameras}
				<Button
					variant="ghost"
					size="sm"
					icon={RefreshCcw}
					label="Refresh the camera sources"
					onclick={onrefreshcameras}
				/>
			{/if}
		</header>
	{/if}
	<div class="px-(--pad-panel) pb-(--pad-panel) {title ? '' : 'pt-(--pad-panel)'}">
		{@render children()}
	</div>
</section>
