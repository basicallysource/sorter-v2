<script lang="ts">
	import type { Snippet } from 'svelte';
	import { createEventDispatcher } from 'svelte';
	import X from '@lucide/svelte/icons/x';

	let {
		open = $bindable(false),
		title,
		wide = false,
		dismissible = true,
		children
	}: {
		open?: boolean;
		title?: string;
		wide?: boolean;
		dismissible?: boolean;
		children?: Snippet;
	} = $props();

	const dispatch = createEventDispatcher<{ close: void }>();

	function close() {
		if (!dismissible) return;
		open = false;
		dispatch('close');
	}

	function handleBackdrop(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			close();
		}
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			close();
		}
	}

	$effect(() => {
		if (!open || typeof window === 'undefined') return;
		window.addEventListener('keydown', handleWindowKeydown);
		return () => window.removeEventListener('keydown', handleWindowKeydown);
	});
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={handleBackdrop}
		role="presentation"
	>
		<div
			class="relative max-h-[90vh] w-full overflow-auto border border-line bg-well {wide ? 'max-w-6xl' : 'max-w-2xl'}"
		>
			<div
				class="sticky top-0 flex items-center justify-between border-b border-line bg-surface px-4 py-3"
			>
				{#if title}
					<h2 class="text-lg font-semibold text-ink">{title}</h2>
				{:else}
					<div></div>
				{/if}
				<button
					onclick={close}
					class="p-1 text-ink transition-colors hover:bg-line"
				>
					<X size={16} />
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
