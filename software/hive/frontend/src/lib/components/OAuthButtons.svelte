<script lang="ts">
	import { api, type AuthOptions } from '$lib/api';
	import BrandMark from '$lib/components/BrandMark.svelte';

	interface Props {
		options: AuthOptions | null;
		next?: string;
		/** Provider name to badge with "Last used" (login page only). */
		lastUsed?: string | null;
	}

	let { options, next, lastUsed = null }: Props = $props();

	function rememberMethod(method: string) {
		try {
			localStorage.setItem('hive:last-login-method', method);
		} catch {
			/* private mode etc. — cosmetic feature, ignore */
		}
	}

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
				onclick={() => rememberMethod(provider.name)}
				class="relative flex w-full items-center justify-center gap-3 border border-border px-4 py-2 text-sm font-medium text-text hover:bg-bg"
			>
				<BrandMark brand={provider.name} />
				{provider.label}
				{#if lastUsed === provider.name}
					<span class="absolute right-2 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">Last used</span>
				{/if}
			</a>
		{/each}
	</div>
{/if}
