<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { ChevronDown, ChevronRight } from 'lucide-svelte';

	interface Props {
		title: string;
		storageKey: string;
		defaultCollapsed?: boolean;
		grow?: boolean;
		actions?: Snippet;
		children: Snippet;
	}

	let { title, storageKey, defaultCollapsed = false, grow = false, actions, children }: Props = $props();

	const storageId = $derived(`sorter.sidebar.collapsed.${storageKey}`);
	let collapsed = $state(false);
	let hydrated = $state(false);

	onMount(() => {
		try {
			const raw = localStorage.getItem(storageId);
			if (raw === '1') collapsed = true;
			else if (raw === '0') collapsed = false;
			else collapsed = defaultCollapsed;
		} catch {
			collapsed = defaultCollapsed;
		}
		hydrated = true;
	});

	function toggle() {
		collapsed = !collapsed;
		if (!hydrated) return;
		try {
			localStorage.setItem(storageId, collapsed ? '1' : '0');
		} catch {
			// ignore storage errors
		}
	}
</script>

<section
	class="flex min-h-0 flex-col border border-border bg-surface"
	style="flex: {collapsed ? '0 0 auto' : grow ? '1 1 auto' : '0 0 auto'};"
>
	<div class="setup-card-header flex shrink-0 items-center justify-between px-3 py-2 text-sm">
		<button
			type="button"
			onclick={toggle}
			class="flex flex-1 items-center gap-2 text-left font-medium text-text hover:text-primary"
			aria-expanded={!collapsed}
		>
			{#if collapsed}
				<ChevronRight size={16} class="text-text-muted" />
			{:else}
				<ChevronDown size={16} class="text-text-muted" />
			{/if}
			<span>{title}</span>
		</button>
		{#if actions}
			<div class="flex items-center gap-3">
				{@render actions()}
			</div>
		{/if}
	</div>
	{#if !collapsed}
		<div class="min-h-0 flex-1 overflow-hidden">
			{@render children()}
		</div>
	{/if}
</section>
