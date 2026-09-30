<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import Lock from '@lucide/svelte/icons/lock';
	import Plus from '@lucide/svelte/icons/plus';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { isEnterprise, isOpen, type Join, type Network, type ScannedNetwork } from '$lib/api';
	import { joinFailure } from '$lib/words';
	import Alert from './Alert.svelte';
	import Badge from './Badge.svelte';
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
		<div class="-ml-3">
			<Button variant="ghost" icon={ChevronLeft} onclick={onback}>Back</Button>
		</div>
	{/if}
	{#if online}
		<Alert tone="success">
			Your Sorter is already online {online.kind === 'ethernet' ? 'by cable' : `on ${online.name}`} at
			<span class="font-mono">{online.address}</span>.
		</Alert>
	{/if}
	{#if failure}
		<Alert tone="danger" title={joinFailure(failure)}>
			{#if failure.reason === 'other' && failure.detail}
				<span class="text-ink-muted">{failure.detail}</span>
			{/if}
		</Alert>
	{/if}

	<h1 class="text-2xl font-semibold tracking-tight text-ink">Choose a Wi-Fi network</h1>

	<div class="flex flex-col gap-2">
		<div class="flex items-center justify-between gap-3">
			<h2 class="label">Networks the Sorter can see</h2>
			<Button icon={RefreshCw} loading={scanning} onclick={onrefresh}>
				{scanning ? 'Scanning' : 'Refresh'}
			</Button>
		</div>

		<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
			{#each networks as net (net.ssid)}
				<li>
					{#if isEnterprise(net)}
						<div class="{row} text-ink-muted">
							<span class="min-w-0 flex-1">
								<span class="block truncate text-base font-medium">{net.ssid}</span>
								<span class="block text-sm">Needs a username. Use a cable instead.</span>
							</span>
							<Lock size={16} />
							<SignalBars signal={net.signal} />
						</div>
					{:else}
						<button type="button" class="{row} hover:bg-hover" onclick={() => onpick(net)}>
							<span class="min-w-0 flex-1 truncate text-base font-medium text-ink">{net.ssid}</span>
							{#if net.saved}<Badge>Saved</Badge>{/if}
							<span class="flex items-center gap-3 text-ink-muted">
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
				<li class="px-4 py-4 text-sm text-ink-muted">
					{scanning ? 'Looking for networks.' : "The Sorter didn't find any networks."}
				</li>
			{/each}
			<li>
				<button type="button" class="{row} hover:bg-hover" onclick={onother}>
					<Plus size={16} class="text-ink-muted" />
					<span class="text-base font-medium text-ink">Other network</span>
				</button>
			</li>
		</ul>
	</div>
</section>
