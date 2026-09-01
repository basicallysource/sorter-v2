<script lang="ts" module>
	// Modals stack: an assembly opens a part on top of itself. Escape has to close
	// the one in front rather than the whole pile, so each open instance registers
	// here and only the last one registered acts on the key.
	const stack: symbol[] = [];
</script>

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

	const token = Symbol('modal');
	$effect(() => {
		if (!open) return;
		stack.push(token);
		return () => {
			const i = stack.lastIndexOf(token);
			if (i >= 0) stack.splice(i, 1);
		};
	});

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape' && stack[stack.length - 1] === token) open = false;
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
