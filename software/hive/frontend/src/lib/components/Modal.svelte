<script lang="ts">
	import type { Snippet } from 'svelte';
	import X from 'lucide-svelte/icons/x';

	interface Props {
		open: boolean;
		title: string;
		children: Snippet;
		onclose?: () => void;
	}

	let { open, title, children, onclose }: Props = $props();

	function handleBackdrop() {
		onclose?.();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose?.();
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onkeydown={handleKeydown}
		onclick={handleBackdrop}
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="mx-4 max-h-[90vh] w-full max-w-lg overflow-y-auto bg-surface p-4 sm:p-6"
			role="dialog"
			aria-modal="true"
			tabindex="-1"
			onkeydown={(e) => e.stopPropagation()}
			onclick={(e) => e.stopPropagation()}
		>
			<div class="mb-4 flex items-start justify-between gap-3">
				<h2 class="min-w-0 text-lg font-semibold text-text">{title}</h2>
				<button
					onclick={onclose}
					aria-label="Close"
					class="shrink-0 text-text-muted hover:text-text"
				>
					<X size={20} />
				</button>
			</div>
			{@render children()}
		</div>
	</div>
{/if}
