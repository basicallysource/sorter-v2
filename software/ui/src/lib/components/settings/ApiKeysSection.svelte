<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Key, Check, AlertTriangle } from 'lucide-svelte';

	const machine = getMachineContext();

	type Provider = {
		id: string;
		label: string;
		envVar: string;
		placeholder: string;
	};

	const PROVIDERS: Provider[] = [
		{
			id: 'google',
			label: 'Google AI (Gemini)',
			envVar: 'GOOGLE_API_KEY',
			placeholder: 'AIza...'
		},
		{
			id: 'openrouter',
			label: 'OpenRouter',
			envVar: 'OPENROUTER_API_KEY',
			placeholder: 'sk-or-v1-...'
		}
	];

	let savedKeys = $state<Record<string, string | null>>({});
	let inputKeys = $state<Record<string, string>>({});
	let saving = $state<Record<string, boolean>>({});
	let statusMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);
	let loading = $state(true);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	async function loadKeys() {
		loading = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/api-keys`);
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			savedKeys = data.keys ?? {};
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load API keys.';
		} finally {
			loading = false;
		}
	}

	async function saveKey(providerId: string) {
		const key = inputKeys[providerId]?.trim();
		if (!key) return;
		saving = { ...saving, [providerId]: true };
		errorMsg = null;
		statusMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/api-keys`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ provider: providerId, key })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			statusMsg = data.message ?? 'Saved.';
			inputKeys[providerId] = '';
			await loadKeys();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save API key.';
		} finally {
			saving = { ...saving, [providerId]: false };
		}
	}

	onMount(() => {
		void loadKeys();
	});
</script>

<div class="grid gap-4">
	{#each PROVIDERS as provider}
		<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface px-3 py-3">
			<div class="flex items-center gap-2">
				<Key size={14} class="dark:text-text-muted-dark text-text-muted" />
				<span class="dark:text-text-dark text-sm font-medium text-text">{provider.label}</span>
				{#if savedKeys[provider.id]}
					<span class="ml-auto flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
						<Check size={12} />
						{savedKeys[provider.id]}
					</span>
				{:else}
					<span class="dark:text-text-muted-dark ml-auto flex items-center gap-1 text-xs text-text-muted">
						<AlertTriangle size={12} />
						Not set
					</span>
				{/if}
			</div>
			<div class="mt-2 flex gap-2">
				<input
					type="password"
					placeholder={provider.placeholder}
					bind:value={inputKeys[provider.id]}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark flex-1 border border-border bg-bg px-2 py-1.5 font-mono text-xs text-text"
				/>
				<button
					type="button"
					onclick={() => void saveKey(provider.id)}
					disabled={!inputKeys[provider.id]?.trim() || saving[provider.id]}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border border-border bg-bg px-3 py-1.5 text-xs text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
				>
					{saving[provider.id] ? 'Saving...' : 'Save'}
				</button>
			</div>
			<div class="dark:text-text-muted-dark mt-1 text-[11px] text-text-muted">
				Overrides <code class="font-mono">{provider.envVar}</code> environment variable
			</div>
		</div>
	{/each}

	{#if errorMsg}
		<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
			{errorMsg}
		</div>
	{/if}
	{#if statusMsg}
		<div class="dark:text-text-muted-dark text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
