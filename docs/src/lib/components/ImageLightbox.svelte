<script lang="ts">
	// Full-size view of a figure from the page body. A native <dialog>, like
	// Modal and SearchModal, so Escape, focus trapping and inert-ing the page
	// are the browser's. Clicking anywhere on it closes it; the link opens the
	// source image in its own tab for anyone who wants to zoom or save it.
	let {
		image = $bindable<{ src: string; alt: string } | null>(null)
	}: { image?: { src: string; alt: string } | null } = $props();

	let dialog: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (image) {
			if (!dialog?.open) dialog?.showModal();
		} else if (dialog?.open) {
			dialog.close();
		}
	});
</script>

<dialog
	class="lightbox"
	aria-label={image?.alt || 'Image'}
	bind:this={dialog}
	onclose={() => (image = null)}
	onclick={(e) => {
		if (!(e.target instanceof HTMLAnchorElement)) image = null;
	}}
>
	{#if image}
		<img class="lightbox-img" src={image.src} alt={image.alt} />
		<div class="lightbox-bar">
			<a href={image.src} target="_blank" rel="noopener">Open original&nbsp;↗</a>
			<button class="lightbox-close" type="button" onclick={() => (image = null)}>Close</button>
		</div>
	{/if}
</dialog>
