<script lang="ts">
	import { ArrowLeft, Printer } from 'lucide-svelte';
	import Seo from '$lib/components/Seo.svelte';
	import HandCutTopPlateGuide from '$lib/components/HandCutTopPlateGuide.svelte';
	import { type Units } from '$lib/handcut';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';

	// A standalone, print-friendly rendering of the same hand-cut guide the
	// lasercut page opens in a modal. No site chrome, no dialog scroll box: on
	// paper it is just the guide, so it can go to the workshop. `?units=mm`
	// picks the unit exactly as the modal deep-link does, so a shared link keeps
	// whichever units the sender was reading.
	let units = $state<Units>('in');
	let urlReady = $state(false);

	onMount(() => {
		const u = page.url.searchParams.get('units');
		if (u === 'mm' || u === 'in') units = u;
		urlReady = true;
	});

	// Mirror the unit choice back into the URL so this page stays shareable.
	// Only write when the URL would actually change: calling replaceState on the
	// first run (before the router has finished initialising after hydration)
	// throws and kills hydration — a dead page where the toggle does nothing and
	// `?units=mm` never applies. The /lasercut modal deep-link guards it the same
	// way, which is why that one works and this one didn't.
	$effect(() => {
		if (!browser || !urlReady) return;
		const params = new URLSearchParams(page.url.search);
		if (units !== 'in') params.set('units', units);
		else params.delete('units');
		const qs = params.toString();
		const target = qs ? `${location.pathname}?${qs}` : location.pathname;
		if (target !== location.pathname + location.search) replaceState(target, {});
	});
</script>

<Seo
	title="Cutting the top plate by hand — printable guide"
	description="A printable, step-by-step guide to cutting the Sorter V2 top plate by hand with a jigsaw, a drill and a tape measure."
/>

<main class="printable-guide mx-auto max-w-4xl px-4 py-6 sm:px-6">
	<!-- toolbar: on screen only, never on paper -->
	<div class="print-hide mb-4 flex flex-wrap items-center justify-between gap-3">
		<a
			href="/lasercut"
			class="inline-flex items-center gap-1.5 text-sm font-medium text-text-muted transition-colors hover:text-text"
		>
			<ArrowLeft size={16} /> Back to laser-cut parts
		</a>
		<button
			class="setup-button-primary inline-flex h-9 items-center gap-1.5 px-3 text-sm font-medium"
			onclick={() => browser && window.print()}
		>
			<Printer size={14} /> Print
		</button>
	</div>

	<header class="mb-4 border-b border-border pb-3">
		<h1 class="text-lg font-bold text-text sm:text-xl">Cutting the top plate by hand</h1>
		<p class="mt-1 text-sm text-text-muted">
			Sorter V2 · jigsaw, drill and a tape measure — no laser needed.
		</p>
	</header>

	<HandCutTopPlateGuide bind:units />
</main>
