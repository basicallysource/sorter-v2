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
	import Panel from '$lib/components/Panel.svelte';
	import Badge from '$lib/components/Badge.svelte';

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
	const reportLine = $derived(
		info && reportedAt
			? current
				? `Reported ${relativeTime(reportedAt)}.`
				: `Last known ${relativeTime(reportedAt)}; it may have changed.`
			: undefined
	);
</script>

{#snippet networkRow(network: MachineNetwork)}
	{@const url = sorterUrl(network.address, info?.ports.ui ?? null)}
	<li class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-(--pad-panel) py-3">
		{#if url}
			<a
				href={url}
				target="_blank"
				rel="noopener noreferrer"
				class="font-mono text-sm wrap-anywhere text-primary-ink hover:underline">{url}</a
			>
		{:else}
			<span class="font-mono text-sm wrap-anywhere text-ink">{network.address}</span>
		{/if}
		<span class="flex items-center gap-2 text-sm text-ink-muted">
			{networkLabel(network)}
			{#if network.internet === false}<Badge tone="warning">No internet</Badge>{/if}
		</span>
	</li>
{/snippet}

<Panel title="Where to find it" description={reportLine} flush>
	{#if !info}
		<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
			{#if everSeen}
				This Sorter hasn't reported where to find it. Updating the Sorter software adds that. If it's up to
				date, check that Network addresses is on in its Hive settings.
			{:else}
				This Sorter hasn't connected to Hive yet.
			{/if}
		</p>
	{:else}
		{#if lan.length === 0 && !nameUrl && tailnet.length === 0}
			<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
				The Sorter reported no network addresses.
			</p>
		{:else}
			<ul class="divide-y divide-line">
				{#each lan as network (network.address)}
					{@render networkRow(network)}
				{/each}
				{#if nameUrl}
					<li class="px-(--pad-panel) py-3">
						<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
							<a
								href={nameUrl}
								target="_blank"
								rel="noopener noreferrer"
								class="font-mono text-sm wrap-anywhere text-primary-ink hover:underline">{nameUrl}</a
							>
							<span class="text-sm text-ink-muted">By name, on the same network</span>
						</div>
						<p class="mt-1 text-sm text-ink-muted">
							The name works on Mac, iPhone and Windows, usually not on Android.
						</p>
					</li>
				{/if}
				{#each tailnet as network (network.address)}
					{@render networkRow(network)}
				{/each}
			</ul>
		{/if}

		{#if apiPort || info.setup_network}
			<div class="flex flex-col gap-1 border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
				{#if apiPort}
					<p>
						For the API, the backend is on port {apiPort}{#if apiUrl}:
							<span class="font-mono wrap-anywhere text-ink">{apiUrl}</span>{/if}
					</p>
				{/if}
				{#if info.setup_network}
					<p>
						It {current ? 'is' : 'was'} also broadcasting its setup network,
						<span class="font-mono text-ink">{info.setup_network.ssid}</span>.
					</p>
				{/if}
			</div>
		{/if}
	{/if}
</Panel>
