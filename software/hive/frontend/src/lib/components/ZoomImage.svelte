<script lang="ts">
	import type { Snippet } from 'svelte';

	// Product-page style hover zoom: renders a thumbnail that, on hover, shows a
	// large floating preview of the same image following the cursor. The preview
	// is portaled to <body> so scrolling/overflow columns never clip it.
	// `zoom` is the preview's width, `aspect` its width over its height (a frame
	// is 16:9, a crop square), and `overlay` is drawn over the picture in the
	// preview, in a box the picture fills (a frame's swatch boxes).
	let {
		src,
		alt = '',
		title = '',
		class: cls = '',
		zoom = 380,
		aspect = 1,
		overlay
	}: {
		src: string;
		alt?: string;
		title?: string;
		class?: string;
		zoom?: number;
		aspect?: number;
		overlay?: Snippet;
	} = $props();

	let show = $state(false);
	let mx = $state(0);
	let my = $state(0);

	const PAD = 10;
	const style = $derived.by(() => {
		if (typeof window === 'undefined') return '';
		// As large as asked, within the window.
		let width = Math.min(zoom, window.innerWidth - 2 * PAD);
		let height = width / aspect;
		if (height > window.innerHeight - 2 * PAD) {
			height = window.innerHeight - 2 * PAD;
			width = height * aspect;
		}
		// Prefer to the right of the cursor; flip left near the right edge.
		let left = mx + 28;
		if (left + width > window.innerWidth - PAD) left = mx - width - 28;
		left = Math.max(PAD, left);
		let top = my - height / 2;
		top = Math.max(PAD, Math.min(top, window.innerHeight - height - PAD));
		return `left:${left}px;top:${top}px;width:${Math.round(width)}px;height:${Math.round(height)}px;`;
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
		class="pointer-events-none fixed z-[60] rounded-panel border border-line bg-raised p-1"
		style={style}
	>
		<div class="relative h-full w-full">
			<img {src} alt="" class="h-full w-full bg-transparent object-contain" />
			{#if overlay}{@render overlay()}{/if}
		</div>
	</div>
{/if}
