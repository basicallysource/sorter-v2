<script lang="ts">
	import { ZoomIn } from 'lucide-svelte';
	import Modal from '$lib/components/Modal.svelte';

	// Generic image: hover shows a magnifier, click opens it full-size in a dimmed
	// modal. Reuse anywhere an inline image benefits from a zoomed view.
	let {
		src,
		alt = '',
		caption = '',
		title = '',
		imgClass = 'max-h-[34vh]'
	}: { src: string; alt?: string; caption?: string; title?: string; imgClass?: string } = $props();

	let open = $state(false);
</script>

<figure class="flex h-full min-h-0 flex-col items-center justify-center gap-2 p-3">
	<button
		type="button"
		class="group relative flex min-h-0 items-center justify-center"
		onclick={() => (open = true)}
		aria-label={title || alt || 'Zoom image'}
	>
		<img {src} {alt} class="{imgClass} w-auto max-w-full object-contain" />
		<span
			class="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100"
		>
			<span class="flex items-center justify-center bg-black/55 p-2 text-white"><ZoomIn size={20} /></span>
		</span>
	</button>
	{#if caption}<figcaption class="text-center text-xs text-text-muted">{caption}</figcaption>{/if}
</figure>

<Modal bind:open title={title || alt}>
	<div class="p-3">
		<img {src} {alt} class="max-h-[82vh] w-full object-contain" />
	</div>
</Modal>
