<script lang="ts">
	import type { Snippet } from 'svelte';

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
		 * Rendered as a chip on the collapsed header so you can still read off
		 * what's filtered without expanding the body.
		 */
		activeLabel?: string | null;
		children: Snippet;
	};

	let { title, storageKey, active = false, activeLabel = null, children }: Props = $props();

	const STORAGE_PREFIX = 'hive.filter.';
	const fullKey = STORAGE_PREFIX + storageKey;

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

<div class="border border-border bg-surface">
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<button
		type="button"
		onclick={toggle}
		class="group flex w-full items-center justify-between gap-2 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text {expanded ? 'border-b border-border bg-bg' : 'hover:bg-bg'}"
		aria-expanded={expanded}
	>
		<span class="flex min-w-0 items-center gap-2">
			<span class="truncate">{title}</span>
			{#if activeLabel && !expanded}
				<span class="border border-primary/30 bg-primary-light px-1 py-0.5 text-[9px] font-medium normal-case tracking-normal text-primary">
					{activeLabel}
				</span>
			{/if}
		</span>
		<svg
			class="h-3 w-3 shrink-0 transition-transform {expanded ? 'rotate-90' : ''}"
			viewBox="0 0 20 20"
			fill="currentColor"
			aria-hidden="true"
		>
			<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 010-1.06L10.94 10 7.21 6.29a.75.75 0 011.08-1.04l4.25 4.25a.75.75 0 010 1.06l-4.25 4.25a.75.75 0 01-1.08-.04z" clip-rule="evenodd" />
		</svg>
	</button>
	{#if expanded}
		<div class="px-1.5 py-2">
			{@render children()}
		</div>
	{/if}
</div>
