<script lang="ts">
	import type { Snippet } from 'svelte';

	// The site's one modal. A native <dialog>, so Escape, the backdrop, focus
	// trapping and inert-ing the page behind it are the browser's job rather than
	// ours — the same thing SearchModal does, factored out so anything else that
	// needs a panel (the part detail, for now) opens the same object.
	let {
		open = $bindable(false),
		title,
		subtitle,
		children
	}: {
		open?: boolean;
		title?: string;
		subtitle?: string;
		children: Snippet;
	} = $props();

	let dialog: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (open) {
			if (!dialog?.open) dialog?.showModal();
		} else if (dialog?.open) {
			dialog.close();
		}
	});
</script>

<dialog
	class="modal"
	bind:this={dialog}
	onclose={() => (open = false)}
	onclick={(e) => {
		if (e.target === dialog) open = false;
	}}
>
	<div class="modal-panel">
		<header class="modal-header">
			<div class="modal-heading">
				<h2 class="modal-title">{title ?? ''}</h2>
				{#if subtitle}<p class="modal-subtitle">{subtitle}</p>{/if}
			</div>
			<button class="modal-close" type="button" onclick={() => (open = false)} aria-label="Close">
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
		<div class="modal-body">
			{@render children()}
		</div>
	</div>
</dialog>
