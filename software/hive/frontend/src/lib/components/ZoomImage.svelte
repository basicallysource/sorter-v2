<script lang="ts">
	// Product-page style hover zoom: renders a thumbnail that, on hover, shows a
	// large floating preview of the same image following the cursor. The preview
	// is portaled to <body> so scrolling/overflow columns never clip it.
	let {
		src,
		alt = '',
		title = '',
		class: cls = '',
		zoom = 380
	}: { src: string; alt?: string; title?: string; class?: string; zoom?: number } = $props();

	let show = $state(false);
	let mx = $state(0);
	let my = $state(0);

	const PAD = 10;
	const style = $derived.by(() => {
		if (typeof window === 'undefined') return '';
		const size = zoom + 10;
		// Prefer to the right of the cursor; flip left near the right edge.
		let left = mx + 28;
		if (left + size > window.innerWidth - PAD) left = mx - size - 28;
		left = Math.max(PAD, left);
		let top = my - size / 2;
		top = Math.max(PAD, Math.min(top, window.innerHeight - size - PAD));
		return `left:${left}px;top:${top}px;width:${zoom}px;height:${zoom}px;`;
	});

	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}
</script>

<img
	{src}
	{alt}
	{title}
	loading="lazy"
	class="{cls} cursor-zoom-in"
	onmouseenter={() => (show = true)}
	onmouseleave={() => (show = false)}
	onmousemove={(e) => {
		mx = e.clientX;
		my = e.clientY;
	}}
/>

{#if show}
	<div
		use:portal
		class="pointer-events-none fixed z-[60] border border-border bg-surface p-1 shadow-xl"
		style={style}
	>
		<img {src} alt="" class="h-full w-full bg-transparent object-contain" />
	</div>
{/if}
