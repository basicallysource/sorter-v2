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
	<div class="setup-panel px-4 py-5">
		<h1 class="text-2xl font-bold break-words text-text">Your Sorter is on {join.ssid}.</h1>
		<div class="mt-4 flex flex-col gap-1 font-mono break-all">
			{#if join.address}
				<span class="text-2xl font-semibold text-text select-all"
					><span class="text-text-muted">http://</span>{join.address}</span
				>
			{/if}
			<span class="text-base text-text-muted select-all">http://{mdns}</span>
		</div>
		<p class="mt-3 text-sm text-text-muted">Tap and hold the address to copy it.</p>
	</div>

	{#if join.internet === false}
		<Alert variant="warning">
			{join.ssid} has no internet.{software.state === 'ready'
				? ''
				: ' The Sorter needs it to finish installing.'}
		</Alert>
	{/if}

	<div class="flex flex-col gap-3">
		<h2 class="text-xs font-semibold tracking-wider text-text-muted uppercase">Next</h2>
		<ol class="flex flex-col gap-3 text-base text-text">
			{#each [`Switch this phone back to ${join.ssid}.`, 'Open the address in Safari or Chrome.'] as step, i (i)}
				<li class="flex items-start gap-3">
					<span
						class="flex h-6 w-6 shrink-0 items-center justify-center border border-border bg-surface font-mono text-xs font-semibold text-text-muted"
						>{i + 1}</span
					>
					<span>{step}</span>
				</li>
			{/each}
		</ol>
		{#if findLink}
			<p class="text-sm text-text-muted">
				Or open <a href={findLink} class="font-medium text-primary underline underline-offset-2"
					>Find my sorter</a
				>, which shows the address once your phone is back online.
			</p>
		{/if}
	</div>

	{#if line}
		<div class="flex items-start gap-3 border border-border bg-surface px-3 py-2.5 text-sm text-text">
			<span class="flex h-5 shrink-0 items-center">
				{#if software.state === 'ready'}
					<Check size={16} class="text-success" />
				{:else if software.state === 'failed'}
					<X size={16} class="text-danger" />
				{:else}
					<Spinner size={14} class="text-text-muted" />
				{/if}
			</span>
			<span>{line}</span>
		</div>
	{/if}

	{#if finished}
		<Alert variant="info">The setup network is closing. Your phone will go back to its own Wi-Fi.</Alert>
	{:else}
		<div class="flex flex-col gap-3">
			{#if finishError}<Alert variant="danger">{finishError}</Alert>{/if}
			<Button variant="primary" wide loading={finishing} onclick={ondone}>Done</Button>
			<Button wide onclick={onchoose}>Choose another network</Button>
		</div>
	{/if}
</section>
