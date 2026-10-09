<script lang="ts">
	import CameraPicture from '$lib/components/CameraPicture.svelte';
	import { indexView } from '$lib/video';

	let {
		source,
		label,
		baseUrl = '',
		fit = 'contain',
		block = false
	}: {
		// A camera's device index, or the URL of a network camera's stream.
		source: number | string | null | undefined;
		label: string;
		baseUrl?: string;
		fit?: 'contain' | 'cover';
		block?: boolean;
	} = $props();

	let stale = $state(false);

	const fitClass = $derived(fit === 'cover' ? 'object-cover' : 'object-contain');
	const layoutClass = $derived(
		block ? 'block aspect-video w-full' : 'absolute inset-0 h-full w-full'
	);
</script>

{#if typeof source === 'number'}
	<CameraPicture
		view={indexView(source)}
		{baseUrl}
		alt={label}
		{fit}
		class={layoutClass}
		bind:stale
	/>
	{#if stale}
		<div
			class="absolute inset-0 flex items-center justify-center bg-well text-sm text-ink-muted"
		>
			No preview
		</div>
	{/if}
{:else if source}
	<img src={source} alt={label} class={`${layoutClass} ${fitClass}`} />
{:else}
	<div class="flex h-full items-center justify-center text-sm text-ink-muted">No preview</div>
{/if}
