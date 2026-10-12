<!--
	docs/overlays.md#lightbox. One picture as big as the window allows, over
	everything, to see a part or a set up close. The picture sits whole on the
	raised plane (its own fill, so a black part on a transparent render still
	shows), its name under it, a close button in the corner. Escape, the close
	button and a click anywhere off the picture close it: there is nothing in
	it to lose. The app opens it by giving `src`, and closes it in `onclose`;
	an app with history makes it a history entry, so Back closes it too.

	<Lightbox src={zoomed?.src} alt={zoomed?.alt} onclose={() => (zoomed = null)} />
-->
<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import Button from './Button.svelte';

	let {
		src = null,
		alt = '',
		onclose
	}: {
		src?: string | null;
		// What the picture is, said under it.
		alt?: string;
		onclose: () => void;
	} = $props();

	let dialog: HTMLDialogElement;

	$effect(() => {
		if (src && !dialog.open) dialog.showModal();
		if (!src && dialog.open) dialog.close();
	});

	// Escape closes the dialog itself; the app hears it here and lets go too.
	function onClosed() {
		if (src) onclose();
	}

	// A click on the dialog's own box, not on the picture or its frame.
	function onclick(event: MouseEvent) {
		if (event.target === dialog) dialog.close();
	}
</script>

<dialog
	bind:this={dialog}
	aria-label={alt || 'Picture'}
	onclose={onClosed}
	{onclick}
	class="m-0 h-dvh max-h-none w-screen max-w-none items-center justify-center bg-transparent p-4 text-ink outline-none backdrop:bg-scrim open:flex sm:p-8"
>
	{#if src}
		<figure
			class="relative flex max-h-full max-w-full flex-col gap-3 rounded-panel border border-line bg-raised p-4"
		>
			<img
				{src}
				alt={alt}
				class="block h-[min(calc(100dvh-10rem),calc(100vw-6rem))] w-[min(calc(100vw-6rem),calc((100dvh-10rem)*4/3))] object-contain"
			/>
			{#if alt}<figcaption class="truncate pr-10 text-sm text-ink-muted">{alt}</figcaption>{/if}
			<div class="absolute right-2 bottom-2">
				<Button variant="ghost" size="sm" icon={X} label="Close" onclick={() => dialog.close()} />
			</div>
		</figure>
	{/if}
</dialog>
