<!--
	docs/overlays.md#modal. The browser's own dialog, so focus stays inside it,
	Escape closes it and the page sits under a scrim. A head with the title
	and a close button, a body that scrolls, and a foot with the actions: the
	way out first, then the one thing to do. A click on the scrim does not
	close it, so a half-filled form is never lost to a stray click; the close
	button and Escape always do.

	<Modal bind:open title="Delete profile">
		<p>...</p>
		{#snippet footer()}
			<Button onclick={() => (open = false)}>Cancel</Button>
			<Button variant="danger">Delete profile</Button>
		{/snippet}
	</Modal>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Button from './Button.svelte';

	let {
		open = $bindable(false),
		title,
		size = 'md',
		onclose,
		children,
		footer
	}: {
		open?: boolean;
		title: string;
		size?: 'sm' | 'md' | 'lg';
		onclose?: () => void;
		children: Snippet;
		footer?: Snippet;
	} = $props();

	const id = `modal-${Math.random().toString(36).slice(2, 9)}`;
	let dialog: HTMLDialogElement;
	const width = $derived({ sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-3xl' }[size]);

	$effect(() => {
		if (open && !dialog.open) dialog.showModal();
		if (!open && dialog.open) dialog.close();
	});

	// Escape, the close button, and closing from outside all end here.
	function onClosed() {
		if (open) open = false;
		onclose?.();
	}
</script>

<dialog
	bind:this={dialog}
	aria-labelledby={id}
	onclose={onClosed}
	class="m-auto max-h-[85dvh] w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-panel border border-line bg-raised p-0 text-ink open:flex {width}"
>
	<header class="flex shrink-0 items-center justify-between gap-4 py-3 pr-3 pl-5">
		<h2 {id} class="text-base font-semibold">{title}</h2>
		<Button variant="ghost" size="sm" icon={X} label="Close" onclick={() => dialog.close()} />
	</header>
	<div class="min-h-0 flex-1 overflow-y-auto px-5 pb-5 text-sm">
		{@render children()}
	</div>
	{#if footer}
		<footer
			class="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3"
		>
			{@render footer()}
		</footer>
	{/if}
</dialog>
