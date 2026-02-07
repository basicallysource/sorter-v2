<script lang="ts">
	import Modal from './Modal.svelte';
	import { settings } from '$lib/stores/settings';
	import { getMachinesContext } from '$lib/machines/context';
	import { backendWsBaseUrl } from '$lib/backend';

	let { open = $bindable(false) } = $props();

	const manager = getMachinesContext();

	let url = $state(`${backendWsBaseUrl}/ws`);

	function handleConnect() {
		manager.connect(url);
	}
</script>

<Modal bind:open title="Settings">
	<div class="flex flex-col gap-6">
		<div>
			<h3 class="dark:text-text-dark mb-2 text-sm font-medium text-text">Connection</h3>
			<div class="mb-3 flex gap-2">
				<input
					type="text"
					bind:value={url}
					placeholder="ws://host:port/ws"
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark flex-1 border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
				<button
					onclick={handleConnect}
					class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-bg"
				>
					Connect
				</button>
			</div>

			{#if manager.machines.size > 0}
				<div class="dark:text-text-muted-dark mb-2 text-xs text-text-muted">
					Connected Machines ({manager.machines.size})
				</div>
				<div class="flex flex-col gap-1">
					{#each [...manager.machines.entries()] as [id, m]}
						<div
							class="dark:border-border-dark dark:bg-bg-dark flex items-center justify-between border border-border bg-bg px-2 py-1.5"
						>
							<div class="flex items-center gap-2">
								<span
									class="h-2 w-2 rounded-full {m.status === 'connected'
										? 'bg-green-500'
										: 'bg-red-500'}"
								></span>
								<span class="dark:text-text-dark text-sm text-text">
									{m.identity?.nickname ?? id.slice(0, 8)}
								</span>
							</div>
							<button
								onclick={() => manager.disconnect(id)}
								class="dark:text-text-muted-dark text-xs text-text-muted hover:text-red-500 dark:hover:text-red-400"
							>
								Disconnect
							</button>
						</div>
					{/each}
				</div>
			{:else}
				<div class="dark:text-text-muted-dark text-sm text-text-muted">No machines connected</div>
			{/if}
		</div>

		<div>
			<h3 class="dark:text-text-dark mb-2 text-sm font-medium text-text">Theme</h3>
			<div class="flex gap-2">
				<button
					onclick={() => settings.setTheme('light')}
					class="flex-1 border px-4 py-2 text-sm transition-colors {$settings.theme === 'light'
						? 'border-blue-500 bg-blue-500/20 text-blue-500'
						: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border-border bg-bg text-text hover:bg-surface'}"
				>
					Light
				</button>
				<button
					onclick={() => settings.setTheme('dark')}
					class="flex-1 border px-4 py-2 text-sm transition-colors {$settings.theme === 'dark'
						? 'border-blue-500 bg-blue-500/20 text-blue-500'
						: 'dark:border-border-dark dark:bg-bg-dark dark:text-text-dark dark:hover:bg-surface-dark border-border bg-bg text-text hover:bg-surface'}"
				>
					Dark
				</button>
			</div>
		</div>
	</div>
</Modal>
