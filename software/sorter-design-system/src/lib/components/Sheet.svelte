<!--
	docs/overlays.md#sheet. A side panel: the full height of the window at
	its right edge, for one thing picked from a list (a set, a part, a
	record) to be read beside the list it came from. There is no scrim and
	the page under it keeps working: it scrolls, and a click on another item
	swaps what the sheet shows. A head with the title, the item's actions and
	a close button, and a body that scrolls on its own. Escape and the close
	button close it; focus goes into it when it opens and back to what had
	it when it closes.

	When the open item is a place worth linking to, the app keeps it in the
	URL and opens the sheet from there, so a reload or a link opens it again
	and Back closes it.

	<Sheet open={!!picked} title={picked?.name ?? ''} onclose={() => (picked = null)}>
		{#snippet actions()}<Button href={picked.url} variant="ghost">Open</Button>{/snippet}
		...
	</Sheet>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Button from './Button.svelte';

	let {
		open,
		title,
		description,
		width = '40rem',
		onclose,
		actions,
		children
	}: {
		open: boolean;
		title: string;
		// One line under the title: what it is, in small type.
		description?: string;
		// Any CSS width; on a narrow window the sheet takes all of it.
		width?: string;
		// The app closes it: Escape and the close button ask through this.
		onclose: () => void;
		actions?: Snippet;
		children: Snippet;
	} = $props();

	const uid = $props.id();
	let sheet: HTMLElement;
	let opener: Element | null = null;

	$effect(() => {
		const showing = sheet.matches(':popover-open');
		if (open && !showing) {
			opener = document.activeElement;
			sheet.showPopover();
			sheet.focus({ preventScroll: true });
		}
		if (!open && showing) {
			sheet.hidePopover();
			if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
			opener = null;
		}
	});

	// Escape closes the sheet unless something on top of it takes the key
	// first: a menu, a select's list, a popover or a modal.
	function onkeydown(event: KeyboardEvent) {
		if (!open || event.key !== 'Escape' || event.defaultPrevented) return;
		const above = [...document.querySelectorAll(':popover-open, dialog[open]')].some((el) => el !== sheet);
		if (!above) onclose();
	}
</script>

<svelte:window {onkeydown} />

<div
	bind:this={sheet}
	popover="manual"
	role="dialog"
	tabindex="-1"
	aria-labelledby="{uid}-title"
	style:width="min({width}, 100vw)"
	class="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none flex-col overflow-hidden border-0 border-l border-line bg-raised p-0 text-ink outline-none [&:popover-open]:flex"
>
	<header class="flex shrink-0 items-start justify-between gap-4 border-b border-line py-3 pr-3 pl-5">
		<div class="flex min-h-(--size-control-sm) min-w-0 flex-col justify-center">
			<h2 id="{uid}-title" class="truncate text-base font-semibold">{title}</h2>
			{#if description}<p class="truncate text-sm text-ink-muted">{description}</p>{/if}
		</div>
		<div class="flex shrink-0 items-center gap-2">
			{#if actions}{@render actions()}{/if}
			<Button variant="ghost" size="sm" icon={X} label="Close" onclick={onclose} />
		</div>
	</header>
	<div class="min-h-0 flex-1 overflow-y-auto">
		{@render children()}
	</div>
</div>
