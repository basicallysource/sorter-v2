<script lang="ts">
	import { Moon, Sun } from 'lucide-svelte';
	import { settings } from '$lib/stores/settings';

	function toggleTheme() {
		settings.setTheme($settings.theme === 'dark' ? 'light' : 'dark');
	}
</script>

<button
	type="button"
	onclick={toggleTheme}
	aria-label={$settings.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
	title={$settings.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
	class="inline-flex items-center gap-2 border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg"
>
	{#if $settings.theme === 'dark'}
		<Sun size={16} />
		<span class="hidden sm:inline">Light</span>
	{:else}
		<Moon size={16} />
		<span class="hidden sm:inline">Dark</span>
	{/if}
</button>
