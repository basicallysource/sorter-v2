<script lang="ts">
	import { X } from 'lucide-svelte';
	import type { Snippet } from 'svelte';

	let {
		open = $bindable(false),
		title,
		bodyScroll = true,
		maxW = 'max-w-3xl',
		children
	}: {
		open?: boolean;
		title?: string;
		bodyScroll?: boolean;
		maxW?: string;
		children: Snippet;
	} = $props();

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') open = false;
	}
</script>

<svelte:window onkeydown={onKey} />

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
		onclick={() => (open = false)}
		onkeydown={() => {}}
		role="presentation"
	>
		<div
			class="setup-card-shell flex max-h-[90vh] w-full {maxW} flex-col border"
			onclick={(e) => e.stopPropagation()}
			onkeydown={() => {}}
			role="dialog"
			aria-modal="true"
			tabindex="-1"
		>
			<div class="setup-card-header flex items-center justify-between border-b border-border px-4 py-2.5">
				<h2 class="text-sm font-semibold text-text">{title ?? ''}</h2>
				<button
					class="setup-button-secondary flex h-8 w-8 items-center justify-center"
					onclick={() => (open = false)}
					aria-label="Close"
				>
					<X size={16} />
				</button>
			</div>
			<div
				class="setup-card-body min-h-0 flex-1 {bodyScroll
					? 'overflow-auto'
					: 'flex flex-col overflow-hidden'}"
			>
				{@render children()}
			</div>
		</div>
	</div>
{/if}
