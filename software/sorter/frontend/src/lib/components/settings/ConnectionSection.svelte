<script lang="ts">
	import { getBackendWsBase } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Plug from '@lucide/svelte/icons/plug';

	const manager = getMachinesContext();

	let url = $state(`${getBackendWsBase()}/ws`);

	function handleConnect() {
		manager.connect(url);
	}
</script>

<Panel title="Connection" description="The machine this page is talking to." flush>
	<div class="divide-y divide-line">
		<div class="px-(--pad-panel) pb-4">
			<Field label="Address" for="machine-address" help="The machine's backend, as ws://host:8000/ws.">
				<div class="flex gap-2">
					<Input
						id="machine-address"
						type="url"
						bind:value={url}
						placeholder="ws://host:port/ws"
						class="min-w-0 flex-1 font-mono"
					/>
					<Button icon={Plug} onclick={handleConnect}>Connect</Button>
				</div>
			</Field>
		</div>
		<div class="px-(--pad-panel) py-4">
			<div class="label">Connected machines</div>
			{#if manager.machines.size > 0}
				<ul class="mt-1 divide-y divide-line">
					{#each [...manager.machines.entries()] as [id, m] (id)}
						{@const chosen = manager.selectedMachineId === id}
						<li class="flex items-center gap-3 py-2">
							<button
								type="button"
								onclick={() => manager.selectMachine(id)}
								aria-pressed={chosen}
								class="flex min-w-0 flex-1 items-center gap-3 rounded-item px-2 py-1.5 text-left transition-colors {chosen
									? 'bg-primary-soft'
									: 'hover:bg-hover'}"
							>
								<span
									class="size-2 shrink-0 rounded-full {m.status === 'connected' ? 'bg-success' : 'bg-danger'}"
									aria-hidden="true"
								></span>
								<span class="min-w-0 flex-1">
									<span class="block truncate text-sm font-medium {chosen ? 'text-primary-ink' : 'text-ink'}">
										{m.identity?.nickname ?? id.slice(0, 8)}
									</span>
									<span class="block truncate font-mono text-sm text-ink-muted">{m.url}</span>
								</span>
							</button>
							<Button size="sm" variant="ghost" onclick={() => manager.disconnect(id)}>Disconnect</Button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="mt-1 text-sm text-ink-muted">No machines connected.</p>
			{/if}
		</div>
	</div>
</Panel>
