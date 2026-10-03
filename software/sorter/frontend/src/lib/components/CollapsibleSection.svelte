<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

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

<!-- A panel whose title opens and closes it, remembered per browser. -->
<section
	class="flex flex-col overflow-hidden rounded-panel bg-surface {grow && !collapsed
		? 'min-h-64'
		: 'min-h-0'}"
	style="flex: {collapsed ? '0 0 auto' : grow ? '1 1 auto' : '0 0 auto'};"
>
	<div class="flex h-(--size-control-lg) shrink-0 items-center justify-between gap-3 pr-2 pl-3">
		<button
			type="button"
			onclick={toggle}
			class="flex h-full flex-1 items-center gap-2 text-left text-sm font-medium text-ink"
			aria-expanded={!collapsed}
		>
			<ChevronRight
				size={16}
				class="shrink-0 text-ink-muted transition-transform {collapsed ? '' : 'rotate-90'}"
			/>
			{title}
		</button>
		{#if actions}
			<div class="flex items-center gap-2">
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
