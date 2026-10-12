<!--
	docs/overlays.md#sheet. A side column: one thing picked from a list (a
	set, a part, a record) read beside the list it came from. It is not over
	the page but part of it: the app puts it in its layout beside the
	content, which narrows and reflows to its left, so every item in the list
	stays in view and a click on another swaps what the sheet shows. It stays
	in place under the top bar while the page scrolls, and its body scrolls on
	its own. A head with the title, the item's actions and a close button.
	Escape and the close button close it; focus goes into it when it opens and
	back to what had it when it closes. On a narrow window there is no room
	beside the list, and it covers the page under the top bar.

	When the open item is a place worth linking to, the app keeps it in the
	URL and opens the sheet from there, so a reload or a link opens it again
	and Back closes it.

	<div class="flex items-start">
		<main class="min-w-0 flex-1">...</main>
		{#if picked}
			<Sheet title={picked.name} onclose={() => (picked = null)}>
				{#snippet actions()}<Button href={picked.url} variant="ghost">Open</Button>{/snippet}
				...
			</Sheet>
		{/if}
	</div>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Button from './Button.svelte';

	let {
		title,
		description,
		width = '40rem',
		onclose,
		actions,
		children
	}: {
		title: string;
		// One line under the title: what it is, in small type.
		description?: string;
		// Any CSS width, beside the content from md up.
		width?: string;
		// The app closes it: Escape and the close button ask through this.
		onclose: () => void;
		actions?: Snippet;
		children: Snippet;
	} = $props();

	const uid = $props.id();
	let sheet: HTMLElement;

	$effect(() => {
		const opener = document.activeElement;
		sheet.focus({ preventScroll: true });
		return () => {
			if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
		};
	});

	// Escape closes the sheet unless something over it takes the key first:
	// a menu, a select's list, a popover or a modal.
	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape' || event.defaultPrevented) return;
		if (document.querySelector(':popover-open, dialog[open]')) return;
		onclose();
	}
</script>

<svelte:window {onkeydown} />

<section
	bind:this={sheet}
	tabindex="-1"
	aria-labelledby="{uid}-title"
	style:--sheet-width={width}
	class="flex flex-col overflow-hidden bg-raised text-ink outline-none max-md:fixed max-md:inset-x-0 max-md:bottom-0 max-md:top-[calc(var(--size-topbar)+1px)] max-md:z-20 md:sticky md:top-[calc(var(--size-topbar)+1px)] md:h-[calc(100dvh-var(--size-topbar)-1px)] md:w-(--sheet-width) md:max-w-[50vw] md:shrink-0 md:border-l md:border-line"
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
</section>
