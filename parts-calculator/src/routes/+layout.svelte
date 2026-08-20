<script lang="ts">
	import './layout.css';
	import { page } from '$app/stores';
	import { Menu, X } from 'lucide-svelte';

	let { children } = $props();

	const tabs = [
		{ href: '/', label: '3D printed parts' },
		{ href: '/framing', label: 'Aluminium framing' },
		{ href: '/lasercut', label: 'Laser cut parts' },
		{ href: '/hardware', label: 'Hardware' },
		{ href: '/assembly', label: 'Machine assembly' }
	];

	const isActive = (href: string) =>
		href === '/' ? $page.url.pathname === '/' : $page.url.pathname.startsWith(href);

	// Five tabs don't fit a phone, so below `sm` they live behind a menu button.
	let menuOpen = $state(false);
	const current = $derived(tabs.find((t) => isActive(t.href))?.label ?? '');

	// Any navigation closes it — including a tap on the tab you're already on,
	// which wouldn't change the pathname, so the click handler covers that too.
	$effect(() => {
		$page.url.pathname;
		menuOpen = false;
	});
</script>

<svelte:head><link rel="icon" href="/favicon.ico" /></svelte:head>
<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') menuOpen = false;
	}}
/>

<header class="relative border-b border-border bg-surface">
	<div class="mx-auto flex max-w-6xl items-center gap-x-6 gap-y-2 px-4 py-3 sm:flex-wrap sm:px-6">
		<a
			href="/"
			class="flex min-w-0 items-center gap-2 text-base font-bold tracking-tight text-text sm:text-lg"
		>
			<img src="/basically-logo.svg" alt="basically" class="h-5 w-auto shrink-0" />
			<span class="truncate">Sorter Parts Calculator</span>
		</a>

		<!-- phone: the menu button, labelled with where you are -->
		<button
			class="ml-auto inline-flex shrink-0 items-center gap-1.5 border border-border px-2.5 py-1.5 text-sm text-text transition-colors hover:border-primary sm:hidden"
			aria-expanded={menuOpen}
			aria-controls="nav-menu"
			onclick={() => (menuOpen = !menuOpen)}
		>
			{#if menuOpen}<X size={16} />{:else}<Menu size={16} />{/if}
			<span class="max-w-[9rem] truncate font-medium">{current}</span>
		</button>

		<!-- desktop: the tabs inline, as before -->
		<nav class="hidden items-center gap-1 sm:flex">
			{#each tabs as tab (tab.href)}
				<a
					href={tab.href}
					class="whitespace-nowrap border-b-2 px-3 py-2 text-sm font-semibold transition-colors {isActive(
						tab.href
					)
						? 'border-primary text-text'
						: 'border-transparent text-text-muted hover:text-text'}"
				>
					{tab.label}
				</a>
			{/each}
		</nav>

	</div>

	{#if menuOpen}
		<!-- click-away layer; sits under the panel but over the page -->
		<button
			class="fixed inset-0 z-30 cursor-default sm:hidden"
			aria-label="Close menu"
			onclick={() => (menuOpen = false)}
		></button>
		<nav
			id="nav-menu"
			class="absolute inset-x-0 top-full z-40 border-b border-border bg-surface shadow-lg sm:hidden"
		>
			{#each tabs as tab (tab.href)}
				<a
					href={tab.href}
					onclick={() => (menuOpen = false)}
					class="block border-l-4 px-4 py-3 text-sm font-semibold transition-colors {isActive(
						tab.href
					)
						? 'border-primary bg-primary/[0.06] text-text'
						: 'border-transparent text-text-muted'}"
				>
					{tab.label}
				</a>
			{/each}
		</nav>
	{/if}
</header>

{@render children()}
