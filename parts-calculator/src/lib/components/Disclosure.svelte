<script lang="ts">
	import { ChevronDown } from 'lucide-svelte';
	import type { Snippet } from 'svelte';

	// A full-width box that says what it holds and opens on click. The dashboard
	// leads with two of them — print settings and build options — so the parts
	// list is what you actually land on, with the settings a click away and
	// their current values readable without opening anything.
	let {
		title,
		summary = '',
		open = $bindable(false),
		flush = false,
		children,
		actions
	}: {
		title: string;
		summary?: string;
		open?: boolean;
		flush?: boolean;
		children: Snippet;
		actions?: Snippet;
	} = $props();

	const uniq = $props.id();
	const bodyId = `disclosure-${uniq}`;
</script>

<div class="setup-panel">
	<div class="flex items-center">
		<button
			type="button"
			class="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg)]"
			onclick={() => (open = !open)}
			aria-expanded={open}
			aria-controls={bodyId}
		>
			<ChevronDown
				size={18}
				class="shrink-0 text-text-muted transition-transform {open ? '' : '-rotate-90'}"
			/>
			<span class="min-w-0">
				<span class="block text-sm font-semibold text-text">{title}</span>
				{#if summary}
					<span class="mt-0.5 block truncate text-xs text-text-muted">{summary}</span>
				{/if}
			</span>
		</button>
		{#if actions && open}
			<div class="shrink-0 pr-4">{@render actions()}</div>
		{/if}
	</div>
	{#if open}
		<div id={bodyId} class="border-t border-border {flush ? '' : 'p-4'}">{@render children()}</div>
	{/if}
</div>
