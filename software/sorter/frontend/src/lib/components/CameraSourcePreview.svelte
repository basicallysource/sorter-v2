<script lang="ts">
	let {
		src,
		label,
		fit = 'contain',
		block = false
	}: {
		src: string | null | undefined;
		label: string;
		fit?: 'contain' | 'cover';
		block?: boolean;
	} = $props();

	const fitClass = $derived(fit === 'cover' ? 'object-cover' : 'object-contain');
	const layoutClass = $derived(
		block ? 'block aspect-video w-full' : 'absolute inset-0 h-full w-full'
	);
</script>

{#if src}
	<img {src} alt={label} class={`${layoutClass} ${fitClass}`} />
{:else}
	<div class="flex h-full items-center justify-center text-sm text-text-muted">No preview</div>
{/if}
