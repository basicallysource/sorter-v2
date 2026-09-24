<script lang="ts">
	import type { MachineNetwork, MachineNetworkInfo } from '$lib/api';
	import {
		isCurrentReport,
		lanNetworks,
		networkLabel,
		sorterUrl,
		tailnetNetworks
	} from '$lib/machineNetwork';
	import { relativeTime } from '$lib/time';

	interface Props {
		info: MachineNetworkInfo | null;
		reportedAt: string | null;
		/** Whether the Sorter has ever sent Hive a heartbeat. */
		everSeen: boolean;
	}

	let { info, reportedAt, everSeen }: Props = $props();

	const current = $derived(isCurrentReport(reportedAt));
	const lan = $derived(info ? lanNetworks(info) : []);
	const tailnet = $derived(info ? tailnetNetworks(info) : []);
	const nameUrl = $derived(info?.mdns ? sorterUrl(info.mdns, info.ports.ui) : null);
	const apiPort = $derived(info?.ports.backend ?? null);
	const apiHost = $derived(lan[0]?.address ?? info?.mdns ?? null);
	const apiUrl = $derived(apiHost ? sorterUrl(apiHost, apiPort) : null);
</script>

{#snippet networkRow(network: MachineNetwork)}
	{@const url = sorterUrl(network.address, info?.ports.ui ?? null)}
	<div
		class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-3 last:border-b-0"
	>
		{#if url}
			<a
				href={url}
				target="_blank"
				rel="noopener noreferrer"
				class="font-mono text-sm wrap-anywhere text-primary hover:underline">{url}</a
			>
		{:else}
			<span class="font-mono text-sm wrap-anywhere text-text">{network.address}</span>
		{/if}
		<span class="flex items-baseline gap-2 text-sm text-text-muted">
			{networkLabel(network)}
			{#if network.internet === false}
				<span class="text-[10px] font-medium tracking-wider text-warning-strong uppercase"
					>No internet</span
				>
			{/if}
		</span>
	</div>
{/snippet}

<section class="mt-6">
	<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
		<h2 class="text-lg font-semibold text-text">Where to find it</h2>
		{#if info && reportedAt}
			<span class="text-xs {current ? 'text-text-muted' : 'text-warning-strong'}">
				{current
					? `Reported ${relativeTime(reportedAt)}`
					: `Last known ${relativeTime(reportedAt)}, may have changed`}
			</span>
		{/if}
	</div>

	{#if !info}
		<div class="mt-3 border border-border bg-surface p-5 text-sm text-text-muted">
			{#if everSeen}
				This Sorter hasn't reported where to find it. Updating the Sorter software adds that. If
				it's up to date, check that Network addresses is on in its Hive settings.
			{:else}
				This Sorter hasn't connected to Hive yet.
			{/if}
		</div>
	{:else}
		{#if lan.length > 0 || nameUrl}
			<div class="mt-3 border border-border bg-surface">
				{#each lan as network}
					{@render networkRow(network)}
				{/each}
				{#if nameUrl}
					<div class="border-b border-border px-4 py-3 last:border-b-0">
						<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
							<a
								href={nameUrl}
								target="_blank"
								rel="noopener noreferrer"
								class="font-mono text-sm wrap-anywhere text-primary hover:underline">{nameUrl}</a
							>
							<span class="text-sm text-text-muted">by name, on the same network</span>
						</div>
						<p class="mt-1 text-xs text-text-muted">
							The name works on Mac, iPhone and Windows, usually not on Android.
						</p>
					</div>
				{/if}
			</div>
		{/if}

		{#if tailnet.length > 0}
			<div class="mt-3 border border-border bg-surface">
				{#each tailnet as network}
					{@render networkRow(network)}
				{/each}
			</div>
		{/if}

		{#if lan.length === 0 && !nameUrl && tailnet.length === 0}
			<div class="mt-3 border border-border bg-surface p-5 text-sm text-text-muted">
				The Sorter reported no network addresses.
			</div>
		{/if}

		{#if apiPort || info.setup_network}
			<div class="mt-2 space-y-1 text-xs text-text-muted">
				{#if apiPort}
					<p>
						For the API, the backend is on port {apiPort}{#if apiUrl}:
							<span class="font-mono wrap-anywhere text-text">{apiUrl}</span>{/if}
					</p>
				{/if}
				{#if info.setup_network}
					<p>
						It {current ? 'is' : 'was'} also broadcasting its setup network,
						<span class="font-mono text-text">{info.setup_network.ssid}</span>.
					</p>
				{/if}
			</div>
		{/if}
	{/if}
</section>
