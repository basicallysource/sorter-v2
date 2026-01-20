<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		open = $bindable(false),
		title,
		children
	}: { open?: boolean; title?: string; children?: Snippet } = $props();

	function close() {
		open = false;
	}

	function handleBackdrop(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			close();
		}
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={handleBackdrop}
		role="presentation"
	>
		<div
			class="dark:border-border-dark dark:bg-bg-dark relative max-h-[90vh] w-full max-w-2xl overflow-auto border border-border bg-bg shadow-lg"
		>
			<div
				class="dark:border-border-dark dark:bg-surface-dark sticky top-0 flex items-center justify-between border-b border-border bg-surface px-4 py-3"
			>
				{#if title}
					<h2 class="dark:text-text-dark text-lg font-semibold text-text">{title}</h2>
				{:else}
					<div></div>
				{/if}
				<button
					onclick={close}
					class="dark:hover:bg-border-dark dark:text-text-dark p-1 text-text transition-colors hover:bg-border"
				>
					✕
				</button>
			</div>
			<div class="p-4">
				{#if children}
					{@render children()}
				{/if}
			</div>
		</div>
	</div>
{/if}
