<script lang="ts">
	// What the Sorter is doing, for anyone who wants to look: collapsed by
	// default, the same on every screen.
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import type { State } from '$lib/api';
	import { cableDetail, softwareDetail, when } from '$lib/words';

	let { state }: { state: State } = $props();

	const join = $derived(state.join);
	const lastJoin = { joining: 'Joining', joined: 'Joined', failed: "Couldn't join" };
	const newestFirst = $derived([...state.events].reverse());
</script>

<details class="group overflow-hidden rounded-panel bg-surface">
	<summary
		class="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 text-sm font-medium text-ink select-none hover:bg-hover [&::-webkit-details-marker]:hidden"
	>
		<ChevronRight size={16} class="text-ink-muted transition-transform group-open:rotate-90" />
		Details
	</summary>

	<div class="flex flex-col gap-4 border-t border-line px-4 py-4 text-sm text-ink">
		<dl class="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-2.5">
			<dt class="text-ink-muted">Name</dt>
			<dd class="min-w-0 break-words">
				{state.sorter.name} <span class="text-ink-muted">({state.sorter.mdns})</span>
			</dd>

			<dt class="text-ink-muted">Networks</dt>
			<dd class="flex min-w-0 flex-col gap-1">
				{#each state.networks as n, i (i)}
					<span class="break-words">
						{n.name}
						<span class="block text-ink-muted">
							<span class="font-mono">{n.address}</span> · {n.internet ? 'has internet' : 'no internet'}
						</span>
					</span>
				{:else}
					<span class="text-ink-muted">None</span>
				{/each}
			</dd>

			<dt class="text-ink-muted">Cable</dt>
			<dd>{cableDetail[state.cable]}</dd>

			<dt class="text-ink-muted">Software</dt>
			<dd class="min-w-0 break-words">{softwareDetail(state.sorter.software)}</dd>

			<dt class="text-ink-muted">Setup network</dt>
			<dd class="min-w-0 break-words">{state.setup_network?.ssid ?? 'Closed'}</dd>

			{#if join}
				<dt class="text-ink-muted">Last join</dt>
				<dd class="min-w-0 break-words">
					{lastJoin[join.state]}
					{join.ssid}{#if join.detail}<span class="block text-ink-muted">{join.detail}</span>{/if}
				</dd>
			{/if}
		</dl>

		<div class="flex flex-col gap-2">
			<h2 class="label">Events</h2>
			<ol class="flex flex-col gap-1.5">
				{#each newestFirst as e, i (i)}
					<li class="grid grid-cols-[6.5rem_1fr] gap-3">
						<span class="num text-ink-muted">{when(e.at, state)}</span>
						<span class="min-w-0 break-words">{e.text}</span>
					</li>
				{:else}
					<li class="text-ink-muted">None yet</li>
				{/each}
			</ol>
		</div>
	</div>
</details>
