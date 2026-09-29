<script lang="ts">
	import { api, type AuthOptions } from '$lib/api';
	import BrandMark from '$lib/components/BrandMark.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';

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
			/* private mode etc.: cosmetic feature, ignore */
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
		<div class="h-px flex-1 bg-line"></div>
		<span class="text-sm text-ink-muted">or</span>
		<div class="h-px flex-1 bg-line"></div>
	</div>

	<div class="flex flex-col gap-2">
		{#each providers as provider (provider.name)}
			<Button href={api.oauthLoginUrl(provider.name, next)} onclick={() => rememberMethod(provider.name)} class="relative w-full">
				<BrandMark brand={provider.name} size={16} />
				{provider.label}
				{#if lastUsed === provider.name}
					<span class="absolute right-2"><Badge tone="primary">Last used</Badge></span>
				{/if}
			</Button>
		{/each}
	</div>
{/if}
