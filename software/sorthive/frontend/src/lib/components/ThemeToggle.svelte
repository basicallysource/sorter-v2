<script lang="ts">
	import { theme } from '$lib/stores/theme';
</script>

<button
	type="button"
	class="inline-flex items-center gap-2 border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-bg)]"
	aria-label={$theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
	title={$theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
	onclick={() => theme.toggle($theme)}
>
	{#if $theme === 'dark'}
		<svg class="h-4 w-4 text-[#FFD500]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
			<circle cx="12" cy="12" r="4" />
			<path stroke-linecap="round" d="M12 2v2.5M12 19.5V22M4.93 4.93l1.77 1.77M17.3 17.3l1.77 1.77M2 12h2.5M19.5 12H22M4.93 19.07l1.77-1.77M17.3 6.7l1.77-1.77" />
		</svg>
		<span>Light</span>
	{:else}
		<svg class="h-4 w-4 text-[var(--color-text-muted)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
			<path stroke-linecap="round" stroke-linejoin="round" d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" />
		</svg>
		<span>Dark</span>
	{/if}
</button>
