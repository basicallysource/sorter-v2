<!--
	docs/overlays.md#modal. The browser's own dialog, so focus stays inside it,
	Escape closes it and the page sits under a scrim. A head with the title
	and a close button, a body that scrolls, and a foot with the actions: the
	way out first, then the one thing to do. A click on the scrim does not
	close it, so a half-filled form is never lost to a stray click; the close
	button and Escape always do.

	`dismissible={false}` is for while something runs that must not be
	interrupted (restarting, powering down): there is no close button, Escape
	does nothing, and the app closes it when the thing is done. `status` says
	what is happening, beside the Spinner at the start of the foot.

	<Modal bind:open title="Delete profile">
		<p>...</p>
		{#snippet footer()}
			<Button onclick={() => (open = false)}>Cancel</Button>
			<Button variant="danger">Delete profile</Button>
		{/snippet}
	</Modal>

	<Modal open={restarting} title="Restarting the machine" dismissible={false}
		status="Waiting for the machine to come back">...</Modal>
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Button from './Button.svelte';
	import Spinner from './Spinner.svelte';

	let {
		open = $bindable(false),
		title,
		size = 'md',
		dismissible = true,
		status,
		onclose,
		children,
		footer
	}: {
		open?: boolean;
		title: string;
		size?: 'sm' | 'md' | 'lg';
		// False while something runs that must not be interrupted.
		dismissible?: boolean;
		// What is happening now, in a few words.
		status?: string;
		onclose?: () => void;
		children: Snippet;
		footer?: Snippet;
	} = $props();

	const uid = $props.id();
	let dialog: HTMLDialogElement;
	const width = $derived({ sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-3xl' }[size]);

	$effect(() => {
		if (open && !dialog.open) dialog.showModal();
		if (!open && dialog.open) dialog.close();
	});

	// When the actions give way to the status, the button that had focus is
	// gone; focus waits on the dialog, so it never falls out of it.
	$effect(() => {
		if (open && !dismissible && !dialog.contains(document.activeElement)) dialog.focus();
	});

	// The browser lets a page refuse only one cancel in a row, so the key
	// itself is stopped too; and if the dialog still closes, it reopens.
	function onkeydown(event: KeyboardEvent) {
		if (open && !dismissible && event.key === 'Escape') event.preventDefault();
	}

	function oncancel(event: Event) {
		if (!dismissible) event.preventDefault();
	}

	// Escape, the close button, and closing from outside all end here.
	function onClosed() {
		if (open && !dismissible) return dialog.showModal();
		if (open) open = false;
		onclose?.();
	}
</script>

<svelte:window {onkeydown} />

<dialog
	bind:this={dialog}
	tabindex="-1"
	aria-labelledby="{uid}-title"
	aria-describedby={status ? `${uid}-status` : undefined}
	{oncancel}
	onclose={onClosed}
	class="m-auto max-h-[85dvh] w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-panel border border-line bg-raised p-0 text-ink outline-none open:flex {width}"
>
	<header class="flex shrink-0 items-center justify-between gap-4 py-3 pr-3 pl-5">
		<h2
			id="{uid}-title"
			class="flex min-h-(--size-control-sm) items-center text-base font-semibold"
		>
			{title}
		</h2>
		{#if dismissible}
			<Button variant="ghost" size="sm" icon={X} label="Close" onclick={() => dialog.close()} />
		{/if}
	</header>
	<div class="min-h-0 flex-1 overflow-y-auto px-5 pb-5 text-sm">
		{@render children()}
	</div>
	{#if footer || status}
		<footer
			class="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3"
		>
			{#if status}
				<p
					id="{uid}-status"
					class="mr-auto flex min-h-(--size-control-sm) items-center gap-2.5 text-sm text-ink"
				>
					<Spinner size={16} class="text-primary-ink" />
					<span aria-live="polite">{status}</span>
				</p>
			{/if}
			{#if footer}{@render footer()}{/if}
		</footer>
	{/if}
</dialog>
