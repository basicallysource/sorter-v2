<script>
	import Modal from './Modal.svelte';
	import { settings } from '$lib/stores/settings';

	let { open = $bindable(false) } = $props();
</script>

<Modal bind:open title="Settings">
	<div>
		<h3 class="dark:text-text-dark mb-2 text-sm font-medium text-text">Theme</h3>
		<div class="flex gap-2">
			<button
				onclick={() => settings.setTheme('light')}
				class="flex-1 border px-4 py-2 transition-colors {$settings.theme === 'light'
					? 'border-blue-500 bg-blue-500/20 text-blue-500'
					: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border-border bg-bg text-text hover:bg-surface'}"
			>
				Light
			</button>
			<button
				onclick={() => settings.setTheme('dark')}
				class="flex-1 border px-4 py-2 transition-colors {$settings.theme === 'dark'
					? 'border-blue-500 bg-blue-500/20 text-blue-500'
					: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border-border bg-bg text-text hover:bg-surface'}"
			>
				Dark
			</button>
		</div>
	</div>
</Modal>
