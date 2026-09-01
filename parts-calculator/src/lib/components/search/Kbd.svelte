<script lang="ts">
	// One keycap. Used for the ⌘K hint on the trigger and the hints along the
	// bottom of the palette, so every shortcut on the site looks like a key.
	let { children, class: cls = '' }: { children: import('svelte').Snippet; class?: string } = $props();
</script>

<kbd
	class="inline-flex h-[1.15rem] min-w-[1.15rem] items-center justify-center border border-border bg-[var(--color-bg)] px-1 font-sans text-[0.6875rem] font-semibold leading-none text-text-muted {cls}"
>
	{@render children()}
</kbd>
