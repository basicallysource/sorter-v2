<script lang="ts">
	import { api, type AuthOptions } from '$lib/api';

	// Brand marks are official path data, kept in this one component on purpose —
	// lucide carries no brand icons, and these should never be redrawn by hand.
	interface Props {
		options: AuthOptions | null;
		next?: string;
	}

	let { options, next }: Props = $props();

	const providers = $derived(
		options
			? ([
					{ name: 'github' as const, label: 'Continue with GitHub', enabled: options.github_enabled },
					{ name: 'discord' as const, label: 'Continue with Discord', enabled: options.discord_enabled }
				].filter((p) => p.enabled))
			: []
	);
</script>

{#if providers.length > 0}
	<div class="my-5 flex items-center gap-3">
		<div class="h-px flex-1 bg-border"></div>
		<span class="text-xs font-medium uppercase tracking-wide text-text-muted">or</span>
		<div class="h-px flex-1 bg-border"></div>
	</div>

	<div class="flex flex-col gap-2">
		{#each providers as provider (provider.name)}
			<a
				href={api.oauthLoginUrl(provider.name, next)}
				class="flex w-full items-center justify-center gap-3 border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
			>
				{#if provider.name === 'github'}
					<svg viewBox="0 0 24 24" class="h-5 w-5 fill-current" aria-hidden="true">
						<path d="M12 .5C5.65.5.5 5.65.5 12A11.5 11.5 0 0 0 8.36 22.7c.58.1.79-.25.79-.56v-2.17c-3.18.69-3.85-1.35-3.85-1.35-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.69.08-.69 1.15.08 1.76 1.19 1.76 1.19 1.02 1.75 2.68 1.24 3.34.95.1-.74.4-1.24.73-1.53-2.54-.29-5.22-1.27-5.22-5.67 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11.03 11.03 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.08 0 4.41-2.68 5.38-5.24 5.66.41.35.78 1.04.78 2.09v3.1c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z"/>
					</svg>
				{:else if provider.name === 'discord'}
					<svg viewBox="0 0 24 24" class="h-5 w-5 fill-current" aria-hidden="true">
						<path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.058a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
					</svg>
				{/if}
				{provider.label}
			</a>
		{/each}
	</div>
{/if}
