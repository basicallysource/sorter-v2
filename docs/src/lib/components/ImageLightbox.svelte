<script lang="ts">
	// Full-size view of a figure from the page body. A native <dialog>, like
	// Modal and SearchModal, so Escape, focus trapping and inert-ing the page
	// are the browser's. Dressed like Modal (same panel and close button) but
	// sized to the image, with the alt text as its caption; the link opens the
	// source in its own tab.
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
		if (e.target === dialog) image = null;
	}}
>
	{#if image}
		<div class="lightbox-panel">
			<button class="modal-close lightbox-close" type="button" onclick={() => (image = null)} aria-label="Close">
				<svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
					<path
						d="M5 5l10 10M15 5L5 15"
						stroke="currentColor"
						stroke-width="1.7"
						stroke-linecap="round"
					/>
				</svg>
			</button>
			<div class="lightbox-body">
				<img class="lightbox-img" src={image.src} alt={image.alt} />
			</div>
			<div class="lightbox-caption">
				{#if image.alt}<p title={image.alt}>{image.alt}</p>{/if}
				<a href={image.src} target="_blank" rel="noopener">Open original&nbsp;↗</a>
			</div>
		</div>
	{/if}
</dialog>
