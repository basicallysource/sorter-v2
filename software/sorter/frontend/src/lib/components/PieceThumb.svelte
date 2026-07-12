<script lang="ts">
	import { Skeleton } from '$lib/components/primitives';

	// A piece image that loads independently of the rest of the page: skeleton
	// pulse while the image fetches, and a part-id chip instead of the browser's
	// broken-image icon when there is no usable image. Fills its parent, so the
	// call site owns the tile's size and border.
	let {
		src = null,
		alt = '',
		fallbackText = ''
	}: { src?: string | null; alt?: string; fallbackText?: string } = $props();

	let loaded = $state(false);
	let failed = $state(false);

	$effect(() => {
		void src;
		loaded = false;
		failed = false;
	});
</script>

<div class="relative h-full w-full">
	{#if src && !failed}
		{#if !loaded}
			<Skeleton class="absolute inset-0" />
		{/if}
		<img
			{src}
			{alt}
			loading="lazy"
			class="h-full w-full object-contain transition-opacity {loaded ? 'opacity-100' : 'opacity-0'}"
			onload={() => (loaded = true)}
			onerror={() => (failed = true)}
		/>
	{:else}
		<div class="flex h-full w-full items-center justify-center overflow-hidden px-1 text-center">
			<span class="truncate text-xs text-[#9A968E]">{fallbackText || '—'}</span>
		</div>
	{/if}
</div>
