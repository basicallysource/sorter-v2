<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import type { CatalogImage } from '$lib/filament';

	// Extra pictures of a thing -- an Onshape screenshot, a section view, a photo
	// of it built. A row of thumbnails; clicking one opens it full-size. Used
	// wherever the catalog carries `images`: parts, hardware, assemblies, their
	// candidates and versions, and planned changes. With `hero` the first image
	// is the thing's main picture and renders large above the rest.
	let { images, hero = false }: { images?: CatalogImage[] | null; hero?: boolean } = $props();
	const rest = $derived(hero ? (images ?? []).slice(1) : (images ?? []));

	let open = $state(false);
	let current = $state<CatalogImage | null>(null);
	function show(im: CatalogImage) {
		current = im;
		open = true;
	}
</script>

{#if images?.length}
	{#if hero}
		{@const main = images[0]}
		<figure class="mb-2">
			<button type="button" class="block w-full cursor-zoom-in" title="Open full-size image" onclick={() => show(main)}>
				<img src={main.url} alt={main.alt} class="h-56 w-full border border-border bg-white object-contain hover:border-primary" />
			</button>
			{#if main.caption}<figcaption class="mt-0.5 text-[11px] text-text-muted">{main.caption}</figcaption>{/if}
		</figure>
	{/if}
	{#if rest.length}
	<div class="flex gap-2 overflow-x-auto">
		{#each rest as im (im.url)}
			<figure class="w-40 shrink-0">
				<button type="button" class="block cursor-zoom-in" title="Open full-size image" onclick={() => show(im)}>
					<img src={im.url} alt={im.alt} class="h-24 w-40 border border-border bg-white object-contain hover:border-primary" />
				</button>
				{#if im.caption}<figcaption class="mt-0.5 truncate text-[10px] text-text-muted" title={im.caption}>{im.caption}</figcaption>{/if}
			</figure>
		{/each}
	</div>
	{/if}
	<Modal bind:open title={current?.alt} maxW="max-w-6xl">
		<div class="flex min-h-0 flex-col items-center justify-center bg-white p-4">
			{#if current}
				<img src={current.url} alt={current.alt} class="max-h-[78vh] max-w-full object-contain" />
				{#if current.caption}<p class="mt-2 text-center text-sm text-text-muted">{current.caption}</p>{/if}
			{/if}
		</div>
	</Modal>
{/if}
