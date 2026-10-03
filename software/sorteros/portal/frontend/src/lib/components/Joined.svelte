<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import type { Join, Software } from '$lib/api';
	import { softwareLine } from '$lib/words';
	import Alert from './Alert.svelte';
	import Button from './Button.svelte';
	import Spinner from './Spinner.svelte';

	let {
		join,
		mdns,
		software,
		findLink,
		finished,
		finishing,
		finishError,
		ondone,
		onchoose
	}: {
		join: Join;
		mdns: string;
		software: Software;
		/** Find my sorter, when this page sent the join and so knows its id. */
		findLink: string | null;
		finished: boolean;
		finishing: boolean;
		finishError: string | null;
		ondone: () => void;
		onchoose: () => void;
	} = $props();

	const line = $derived(softwareLine(software, join.internet));
</script>

<section class="flex flex-col gap-6">
	<div class="rounded-panel bg-surface px-4 py-5">
		<h1 class="text-2xl font-semibold tracking-tight break-words text-ink">
			Your Sorter is on {join.ssid}.
		</h1>
		<div class="mt-4 flex flex-col gap-1 font-mono break-all">
			{#if join.address}
				<span class="text-2xl font-medium text-ink select-all"
					><span class="text-ink-muted">http://</span>{join.address}</span
				>
			{/if}
			<span class="text-base text-ink-muted select-all">http://{mdns}</span>
		</div>
		<p class="mt-3 text-sm text-ink-muted">Tap and hold the address to copy it.</p>
	</div>

	{#if join.internet === false}
		<Alert tone="warning">
			{join.ssid} has no internet.{software.state === 'ready'
				? ''
				: ' The Sorter needs it to finish installing.'}
		</Alert>
	{/if}

	<div class="flex flex-col gap-3">
		<h2 class="label">Next</h2>
		<ol class="flex flex-col gap-3 text-base text-ink">
			{#each [`Switch this phone back to ${join.ssid}.`, 'Open the address in Safari or Chrome.'] as step, i (i)}
				<li class="flex items-start gap-3">
					<span
						class="num flex size-6 shrink-0 items-center justify-center rounded-badge bg-surface text-xs font-semibold text-ink-muted"
						>{i + 1}</span
					>
					<span>{step}</span>
				</li>
			{/each}
		</ol>
		{#if findLink}
			<p class="text-sm text-ink-muted">
				Or open <a href={findLink} class="font-medium text-primary-ink underline underline-offset-2"
					>Find my sorter</a
				>, which shows the address once your phone is back online.
			</p>
		{/if}
	</div>

	{#if line}
		<div class="flex items-start gap-3 rounded-panel bg-surface px-4 py-3 text-sm text-ink">
			<span class="flex h-5 shrink-0 items-center">
				{#if software.state === 'ready'}
					<Check size={16} class="text-success-ink" />
				{:else if software.state === 'failed'}
					<X size={16} class="text-danger-ink" />
				{:else}
					<Spinner size={14} class="text-ink-muted" />
				{/if}
			</span>
			<span>{line}</span>
		</div>
	{/if}

	{#if finished}
		<Alert tone="info">The setup network is closing. Your phone will go back to its own Wi-Fi.</Alert>
	{:else}
		<div class="flex flex-col gap-3">
			{#if finishError}<Alert tone="danger">{finishError}</Alert>{/if}
			<Button variant="primary" size="lg" class="w-full" loading={finishing} onclick={ondone}
				>Done</Button
			>
			<Button size="lg" class="w-full" onclick={onchoose}>Choose another network</Button>
		</div>
	{/if}
</section>
