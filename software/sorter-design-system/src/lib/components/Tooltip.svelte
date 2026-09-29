<!--
	docs/overlays.md#tooltip. A short name for something with no room for one:
	a truncated value, a chart's mark, a status dot. Never an explanation a
	setting needs; that goes under the setting, where it is always visible.
	An icon Button already names itself with `label`.

	It shows after a short pause under the pointer, at once on keyboard
	focus, and hides on Escape. The trigger snippet gets the attribute that
	ties the element to the text; spread it on a focusable element:

	<Tooltip text="Plate, Round 1 x 1 with Flower Edge">
		{#snippet children(props)}<a {...props} href="/parts/24866" class="truncate">...</a>{/snippet}
	</Tooltip>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { place, type Placement } from './place';

	let {
		text,
		placement = 'top',
		children
	}: {
		text: string;
		placement?: Placement;
		children: Snippet<[{ 'aria-describedby': string }]>;
	} = $props();

	const uid = $props.id();
	const id = `${uid}-tip`;
	let anchor: HTMLElement;
	let tip: HTMLElement;
	let timer: ReturnType<typeof setTimeout> | undefined;

	function show(delay: number) {
		clearTimeout(timer);
		timer = setTimeout(() => {
			if (!tip.matches(':popover-open')) tip.showPopover();
			const at = place(anchor.getBoundingClientRect(), tip.getBoundingClientRect(), placement);
			tip.style.top = `${at.top}px`;
			tip.style.left = `${at.left}px`;
		}, delay);
	}

	function hide() {
		clearTimeout(timer);
		if (tip?.matches(':popover-open')) tip.hidePopover();
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') hide();
	}
</script>

<svelte:window {onkeydown} />

<span
	bind:this={anchor}
	class="inline-flex max-w-full min-w-0"
	role="presentation"
	onpointerenter={() => show(450)}
	onpointerleave={hide}
	onfocusin={() => show(0)}
	onfocusout={hide}
>
	{@render children({ 'aria-describedby': id })}
</span>

<div
	bind:this={tip}
	{id}
	popover="manual"
	role="tooltip"
	class="pointer-events-none fixed inset-auto m-0 max-w-72 rounded-control border border-line bg-raised px-2.5 py-1.5 text-sm text-ink"
>
	{text}
</div>
