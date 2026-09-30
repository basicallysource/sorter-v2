<!--
	docs/overlays.md#popover. A panel that opens from a button and holds a
	little content: a color picker, a short form, an explanation. It floats,
	so it is the raised plane: a fill and one line, no shadow. The browser's
	popover attribute gives it the top layer, closing on a click outside or
	Escape, and focus returning to the button.

	The trigger snippet gets the attributes that wire its button to the
	panel; spread them onto it:

	<Popover label="Theme color">
		{#snippet trigger(props)}<Button {...props}>Color</Button>{/snippet}
		...content...
	</Popover>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { place, type Placement } from './place';

	type TriggerProps = {
		popovertarget: string;
		'aria-expanded': boolean;
		'aria-haspopup': 'dialog';
	};

	let {
		trigger,
		children,
		label,
		placement = 'bottom-start',
		width = '20rem',
		padded = true,
		open = $bindable(false)
	}: {
		trigger: Snippet<[TriggerProps]>;
		children: Snippet;
		// The panel's accessible name.
		label: string;
		placement?: Placement;
		// Any CSS width; 'auto' fits the content.
		width?: string;
		// False for content that runs to the panel's edges (a list).
		padded?: boolean;
		open?: boolean;
	} = $props();

	const uid = $props.id();
	const id = `${uid}-popover`;
	let anchor: HTMLElement;
	let panel: HTMLElement;

	function position() {
		const at = place(anchor.getBoundingClientRect(), panel.getBoundingClientRect(), placement);
		panel.style.top = `${at.top}px`;
		panel.style.left = `${at.left}px`;
	}

	function ontoggle(event: ToggleEvent) {
		open = event.newState === 'open';
		if (open) position();
	}

	// Keep it on its button while the page scrolls or the window changes size.
	$effect(() => {
		if (!open) return;
		const follow = () => position();
		window.addEventListener('scroll', follow, true);
		window.addEventListener('resize', follow);
		return () => {
			window.removeEventListener('scroll', follow, true);
			window.removeEventListener('resize', follow);
		};
	});

	// Opening or closing from outside (bind:open) drives the panel.
	$effect(() => {
		if (!panel) return;
		const showing = panel.matches(':popover-open');
		if (open && !showing) panel.showPopover();
		if (!open && showing) panel.hidePopover();
	});
</script>

<span bind:this={anchor} class="inline-flex">
	{@render trigger({ popovertarget: id, 'aria-expanded': open, 'aria-haspopup': 'dialog' })}
</span>

<div
	bind:this={panel}
	{id}
	popover="auto"
	role="dialog"
	aria-label={label}
	{ontoggle}
	style:width
	class="fixed inset-auto m-0 max-w-[calc(100vw-1rem)] rounded-panel border border-line bg-raised text-sm text-ink {padded
		? 'p-4'
		: 'p-0'}"
>
	{@render children()}
</div>
