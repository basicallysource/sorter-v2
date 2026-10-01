<script lang="ts">
	import type { Snippet } from 'svelte';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	type Props = {
		title: string;
		/**
		 * Stable identifier — used as the localStorage suffix. Pick something
		 * that won't collide with other groups across pages.
		 */
		storageKey: string;
		/**
		 * True when this group currently constrains the listing. Drives the
		 * auto-expand behaviour: if the user has no explicit open/closed
		 * preference saved yet, an active group starts expanded.
		 */
		active?: boolean;
		/**
		 * Short label of the active selection (e.g. "Conflict", "Underexposed").
		 * Shown on the collapsed header so you can still read off what's
		 * filtered without expanding the body.
		 */
		activeLabel?: string | null;
		children: Snippet;
	};

	let { title, storageKey, active = false, activeLabel = null, children }: Props = $props();

	const STORAGE_PREFIX = 'hive.filter.';
	const fullKey = $derived(STORAGE_PREFIX + storageKey);

	// null = no user preference saved yet → fall back to auto-expand rule.
	// true / false = user explicitly toggled; honor that even when the
	// active state changes later.
	let userPref = $state<boolean | null>(null);

	$effect(() => {
		// Only run once on mount, but $effect re-runs on storageKey change too
		// which is fine since each FilterGroup mounts once with a stable key.
		if (typeof window === 'undefined') return;
		try {
			const raw = window.localStorage.getItem(fullKey);
			if (raw === '1') userPref = true;
			else if (raw === '0') userPref = false;
			else userPref = null;
		} catch {
			userPref = null;
		}
	});

	const expanded = $derived(userPref === null ? active : userPref);

	function toggle() {
		const next = !expanded;
		userPref = next;
		if (typeof window === 'undefined') return;
		try {
			window.localStorage.setItem(fullKey, next ? '1' : '0');
		} catch {
			// Quota exceeded / disabled storage — UI still works, just won't persist.
		}
	}
</script>

<!-- One filter in a filter column: a heading that opens and closes (remembered
     in this browser), the current choice beside it while closed, and the
     choices under it. Groups sit in a divided list on the column's surface. -->
<div>
	<button
		type="button"
		onclick={toggle}
		aria-expanded={expanded}
		class="flex h-(--size-nav-item) w-full items-center gap-2 px-(--pad-control-sm) text-left text-sm font-medium text-ink hover:bg-hover"
	>
		<ChevronRight size={16} class="shrink-0 text-ink-muted transition-transform {expanded ? 'rotate-90' : ''}" />
		<span class="min-w-0 flex-1 truncate">{title}</span>
		{#if active && activeLabel && !expanded}<span class="max-w-[60%] truncate text-sm font-normal text-primary-ink">{activeLabel}</span>{/if}
	</button>
	{#if expanded}
		<div class="px-1.5 pb-2">{@render children()}</div>
	{/if}
</div>
