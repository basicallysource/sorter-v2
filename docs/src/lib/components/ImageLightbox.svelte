<script lang="ts">
	// Full-size view of a figure from the page body. A native <dialog>, like
	// Modal and SearchModal, so Escape, focus trapping and inert-ing the page
	// are the browser's. Dressed like Modal (same header, close button and
	// panel) but sized to the image; the link opens the source in its own tab.
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
			<header class="modal-header">
				<div class="modal-heading">
					<h2 class="lightbox-title" title={image.alt}>{image.alt || 'Image'}</h2>
					<p class="modal-subtitle">
						<a href={image.src} target="_blank" rel="noopener">Open original&nbsp;↗</a>
					</p>
				</div>
				<button class="modal-close" type="button" onclick={() => (image = null)} aria-label="Close">
					<svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
						<path
							d="M5 5l10 10M15 5L5 15"
							stroke="currentColor"
							stroke-width="1.7"
							stroke-linecap="round"
						/>
					</svg>
				</button>
			</header>
			<div class="lightbox-body">
				<img class="lightbox-img" src={image.src} alt={image.alt} />
			</div>
		</div>
	{/if}
</dialog>
