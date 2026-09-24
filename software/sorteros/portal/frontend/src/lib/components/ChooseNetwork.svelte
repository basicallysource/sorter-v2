<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import Lock from '@lucide/svelte/icons/lock';
	import Plus from '@lucide/svelte/icons/plus';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { isEnterprise, isOpen, type Join, type Network, type ScannedNetwork } from '$lib/api';
	import { joinFailure } from '$lib/words';
	import Alert from './Alert.svelte';
	import Button from './Button.svelte';
	import SignalBars from './SignalBars.svelte';

	let {
		networks,
		scanning,
		online,
		failure,
		onrefresh,
		onpick,
		onother,
		onback
	}: {
		networks: ScannedNetwork[];
		scanning: boolean;
		/** A network the Sorter already has internet through, if any. */
		online: Network | null;
		failure: Join | null;
		onrefresh: () => void;
		onpick: (net: ScannedNetwork) => void;
		onother: () => void;
		/** Back to the network the Sorter joined, when this list replaces it. */
		onback?: () => void;
	} = $props();

	const row = 'flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left';
</script>

<section class="flex flex-col gap-5">
	{#if onback}
		<button
			type="button"
			class="-my-2 -ml-2 inline-flex min-h-11 items-center gap-1 self-start px-2 text-sm font-medium text-text-muted hover:text-text"
			onclick={onback}
		>
			<ChevronLeft size={16} />
			Back
		</button>
	{/if}
	{#if online}
		<Alert variant="success">
			Your Sorter is already online {online.kind === 'ethernet' ? 'by cable' : `on ${online.name}`} at
			<span class="font-mono">{online.address}</span>.
		</Alert>
	{/if}
	{#if failure}
		<Alert variant="danger">
			<p class="font-medium">{joinFailure(failure)}</p>
			{#if failure.reason === 'other' && failure.detail}
				<p class="text-text-muted">{failure.detail}</p>
			{/if}
		</Alert>
	{/if}

	<h1 class="text-2xl font-bold text-text">Choose a Wi-Fi network</h1>

	<div class="flex flex-col gap-2">
		<div class="flex items-center justify-between gap-3">
			<h2 class="text-xs font-semibold tracking-wider text-text-muted uppercase">
				Networks the Sorter can see
			</h2>
			<Button onclick={onrefresh} loading={scanning}>
				{#if !scanning}<RefreshCw size={14} />{/if}
				{scanning ? 'Scanning' : 'Refresh'}
			</Button>
		</div>

		<ul class="setup-panel divide-y divide-border">
			{#each networks as net (net.ssid)}
				<li>
					{#if isEnterprise(net)}
						<div class="{row} text-text-muted">
							<span class="min-w-0 flex-1">
								<span class="block truncate text-base font-medium">{net.ssid}</span>
								<span class="block text-sm">Needs a username. Use a cable instead.</span>
							</span>
							<Lock size={16} />
							<SignalBars signal={net.signal} />
						</div>
					{:else}
						<button type="button" class="{row} hover:bg-bg" onclick={() => onpick(net)}>
							<span class="min-w-0 flex-1 truncate text-base font-medium text-text">{net.ssid}</span>
							{#if net.saved}
								<span class="border border-border px-1.5 py-0.5 text-xs font-medium text-text-muted">
									Saved
								</span>
							{/if}
							<span class="flex items-center gap-3 text-text-muted">
								{#if isOpen(net)}
									<span class="text-sm">Open</span>
								{:else}
									<Lock size={16} aria-label="Needs a password" />
								{/if}
								<SignalBars signal={net.signal} />
							</span>
						</button>
					{/if}
				</li>
			{:else}
				<li class="px-4 py-4 text-sm text-text-muted">
					{scanning ? 'Looking for networks.' : "The Sorter didn't find any networks."}
				</li>
			{/each}
			<li>
				<button type="button" class="{row} hover:bg-bg" onclick={onother}>
					<Plus size={16} class="text-text-muted" />
					<span class="text-base font-medium text-text">Other network</span>
				</button>
			</li>
		</ul>
	</div>
</section>
