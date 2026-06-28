<script lang="ts">
	import type { Snippet } from 'svelte';
	import { tick } from 'svelte';

	// Viewport-aware hover/focus popover. The panel renders with `position: fixed`
	// and is clamped so it is ALWAYS fully inside the viewport — it flips above/
	// below the trigger depending on room, and shifts horizontally so it never
	// clips off-screen. Unlike a plain `absolute` tooltip it is not cut off by any
	// ancestor's `overflow`, because fixed positioning is relative to the viewport.
	let {
		trigger,
		children,
		placement = 'top',
		gap = 6,
		panelClass = 'max-w-xs',
		class: className = ''
	}: {
		trigger: Snippet;
		children: Snippet;
		placement?: 'top' | 'bottom';
		gap?: number;
		panelClass?: string;
		class?: string;
	} = $props();

	const MARGIN = 8; // keep this far from every viewport edge

	let visible = $state(false);
	let ready = $state(false); // positioned yet? avoids a flash at (0,0)
	let top = $state(0);
	let left = $state(0);
	let triggerEl = $state<HTMLElement | null>(null);
	let panelEl = $state<HTMLElement | null>(null);

	async function reposition() {
		if (!visible || !triggerEl) return;
		await tick(); // wait for the panel to render so we can measure it
		const t = triggerEl.getBoundingClientRect();
		const panel = panelEl?.getBoundingClientRect();
		const pw = panel?.width ?? 0;
		const ph = panel?.height ?? 0;
		const vw = window.innerWidth;
		const vh = window.innerHeight;

		const above = t.top - gap - ph;
		const below = t.bottom + gap;
		let placeTop =
			placement === 'top'
				? above >= MARGIN
					? above
					: below
				: below + ph <= vh - MARGIN
					? below
					: above;
		placeTop = Math.max(MARGIN, Math.min(placeTop, vh - ph - MARGIN));

		// Align the panel's left edge to the trigger, then clamp into the viewport.
		let placeLeft = Math.max(MARGIN, Math.min(t.left, vw - pw - MARGIN));

		top = placeTop;
		left = placeLeft;
		ready = true;
	}

	function show() {
		visible = true;
		ready = false;
		reposition();
	}

	function hide() {
		visible = false;
		ready = false;
	}

	// Keep it pinned to the trigger while open if the page scrolls/resizes.
	$effect(() => {
		if (!visible) return;
		const onMove = () => reposition();
		window.addEventListener('scroll', onMove, true);
		window.addEventListener('resize', onMove);
		return () => {
			window.removeEventListener('scroll', onMove, true);
			window.removeEventListener('resize', onMove);
		};
	});
</script>

<span
	bind:this={triggerEl}
	class="inline-flex {className}"
	onmouseenter={show}
	onmouseleave={hide}
	onfocusin={show}
	onfocusout={hide}
	role="presentation"
>
	{@render trigger()}
</span>

{#if visible}
	<div
		bind:this={panelEl}
		class="pointer-events-none fixed z-50 border border-border bg-surface px-3 py-2 text-sm leading-snug whitespace-normal text-text shadow-md {panelClass} {ready
			? ''
			: 'opacity-0'}"
		style="top: {top}px; left: {left}px;"
		role="tooltip"
	>
		{@render children()}
	</div>
{/if}
