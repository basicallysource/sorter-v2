<script lang="ts">
	import Modal from './Modal.svelte';
	import { settings } from '$lib/stores/settings';
	import { getMachinesContext } from '$lib/machines/context';
	import { backendWsBaseUrl } from '$lib/backend';
    import { backendHttpBaseUrl } from '$lib/backend';

	let { open = $bindable(false) } = $props();

	const manager = getMachinesContext();

	let url = $state(`${backendWsBaseUrl}/ws`);

	function handleConnect() {
		manager.connect(url);
	}

	const manualSteppers = [
		{ key: 'c_channel_1', label: 'C Channel 1' },
		{ key: 'c_channel_2', label: 'C Channel 2' },
		{ key: 'c_channel_3', label: 'C Channel 3' },
		{ key: 'carousel', label: 'Carousel' },
		{ key: 'chute', label: 'Chute' }
	] as const;

	let pulseDuration = $state(0.25);
	let pulseSpeed = $state(800);
	let pulsing = $state<Record<string, boolean>>({});
	let stopping = $state<Record<string, boolean>>({});

	async function pulse(stepper: string, direction: 'cw' | 'ccw') {
		const key = `${stepper}:${direction}`;
		pulsing = { ...pulsing, [key]: true };
		try {
			const params = new URLSearchParams({
				stepper,
				direction,
				duration_s: String(pulseDuration),
				speed: String(pulseSpeed)
			});
			const res = await fetch(`${backendHttpBaseUrl}/stepper/pulse?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				const errText = await res.text();
				console.error(`Pulse failed for ${stepper} ${direction}:`, errText);
			}
		} catch (e) {
			console.error(`Pulse request failed for ${stepper} ${direction}:`, e);
		} finally {
			pulsing = { ...pulsing, [key]: false };
		}
	}

	async function stop(stepper: string) {
		stopping = { ...stopping, [stepper]: true };
		try {
			const params = new URLSearchParams({ stepper });
			const res = await fetch(`${backendHttpBaseUrl}/stepper/stop?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				const errText = await res.text();
				console.error(`Stop failed for ${stepper}:`, errText);
			}
		} catch (e) {
			console.error(`Stop request failed for ${stepper}:`, e);
		} finally {
			stopping = { ...stopping, [stepper]: false };
		}
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

		<div>
			<h3 class="dark:text-text-dark mb-2 text-sm font-medium text-text">Manual Stepper Pulse</h3>
			<div class="mb-3 grid grid-cols-2 gap-2">
				<label class="dark:text-text-dark text-xs text-text">
					Duration (s)
					<input
						type="number"
						min="0.05"
						max="5"
						step="0.05"
						bind:value={pulseDuration}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
				</label>
				<label class="dark:text-text-dark text-xs text-text">
					Speed
					<input
						type="number"
						min="1"
						step="50"
						bind:value={pulseSpeed}
						class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
					/>
				</label>
			</div>

			<div class="flex flex-col gap-2">
				{#each manualSteppers as s}
					<div class="dark:border-border-dark dark:bg-bg-dark grid grid-cols-[1fr_auto_auto_auto] items-center gap-2 border border-border bg-bg px-2 py-2">
						<span class="dark:text-text-dark text-sm text-text">{s.label}</span>
						<button
							onclick={() => pulse(s.key, 'cw')}
							disabled={Boolean(pulsing[`${s.key}:cw`])}
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
						>
							Pulse CW
						</button>
						<button
							onclick={() => pulse(s.key, 'ccw')}
							disabled={Boolean(pulsing[`${s.key}:ccw`])}
							class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark cursor-pointer border border-border bg-surface px-3 py-1.5 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
						>
							Pulse CCW
						</button>
						<button
							onclick={() => stop(s.key)}
							disabled={Boolean(stopping[s.key])}
							class="cursor-pointer border border-red-500 bg-red-500/20 px-3 py-1.5 text-xs text-red-600 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
						>
							Stop
						</button>
					</div>
				{/each}
			</div>
		</div>
	</div>
</Modal>
