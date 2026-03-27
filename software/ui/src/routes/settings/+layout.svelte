<script lang="ts">
	import { page } from '$app/state';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { settingsNavItems } from '$lib/settings/stations';

	let { children } = $props();
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-4 sm:p-6">
	<AppHeader />

	<div class="flex flex-col gap-4 lg:flex-row lg:gap-6">
		<nav class="w-full lg:w-48 lg:flex-shrink-0">
			<div class="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
				{#each settingsNavItems as item}
					{@const active = page.url.pathname === item.href}
					<a
						href={item.href}
						aria-current={active ? 'page' : undefined}
						class="flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors {active
							? 'dark:bg-surface-dark dark:text-text-dark bg-surface font-medium text-text'
							: 'dark:text-text-muted-dark dark:hover:bg-surface-dark text-text-muted hover:bg-surface'}"
					>
						<item.icon size={16} />
						{item.label}
					</a>
				{/each}
			</div>
		</nav>

		<div class="min-w-0 flex-1">
			{@render children()}
		</div>
	</div>
</div>
