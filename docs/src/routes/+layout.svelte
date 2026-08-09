<script lang="ts">
	import './layout.css';
	import { page } from '$app/state';
	import NavTree from '$lib/components/NavTree.svelte';

	let { data, children } = $props();

	let modal: HTMLDialogElement | undefined = $state();
	let sidebarOpen = $state(false);

	const fm = $derived(page.data.page?.fm ?? {});
	const currentUrl = $derived(page.url.pathname);
	const currentSection = $derived(data.nav.find((s) => s.id === fm.section));
	const sidebarHasContent = $derived(
		!!currentSection &&
			(currentSection.pages.length > 1 || (currentSection.groups?.length ?? 0) > 0)
	);
</script>

<div class="shell">
	<header class="site-header">
		<a class="brand" href="/">
			<img class="brand-logo" src="/assets/basically-logo.svg" alt="basically logo" width="26" height="24" />
			<span>
				<strong>Sorter V2</strong>
				<small>Documentation</small>
			</span>
		</a>
		<button type="button" class="construction-banner" onclick={() => modal?.showModal()}>
			<span class="construction-banner-icon" aria-hidden="true">⚠</span>
			<span class="construction-banner-text">
				<strong>Under heavy construction</strong>
				<small>Docs are incomplete &amp; may be inaccurate — don't build Sorter yet.</small>
			</span>
			<span class="construction-banner-chevron" aria-hidden="true">▾</span>
		</button>
		<nav class="site-nav" aria-label="Primary">
			<a href="/" aria-current={currentUrl === '/' ? 'page' : undefined}>Overview</a>
			{#each data.nav as section (section.id)}
				<a href={section.url} aria-current={fm.section === section.id ? 'page' : undefined}>
					{section.title}
				</a>
			{/each}
		</nav>
	</header>

	<dialog class="construction-modal" bind:this={modal} onclick={(e) => e.target === modal && modal?.close()}>
		<div class="construction-modal-inner">
			<div class="construction-modal-head">
				<h2>⚠ Under heavy construction</h2>
				<form method="dialog">
					<button class="construction-modal-close" aria-label="Close">✕</button>
				</form>
			</div>
			<p>As of July 11, 2026, Sorter V2 is not yet in a position to be built.</p>
			<p>
				The documentation that exists is incomplete. Any given page may be accurate, inaccurate,
				present only as an example, or badly out of date. We do not yet recommend that anyone
				attempt to build Sorter.
			</p>
			<p class="construction-modal-discord">
				For the most live updates on our progress,
				<a href="https://discord.gg/6PZtqkwtaS" target="_blank" rel="noopener">join our Discord&nbsp;↗</a>.
			</p>
		</div>
	</dialog>

	{#if sidebarHasContent && currentSection}
		<div class="layout-with-sidebar">
			<aside class="section-sidebar" class:nav-open={sidebarOpen} aria-label="{currentSection.title} navigation">
				<button
					type="button"
					class="section-sidebar-toggle"
					aria-expanded={sidebarOpen}
					onclick={() => (sidebarOpen = !sidebarOpen)}
				>
					<span>{currentSection.title}</span>
					<span class="section-sidebar-toggle-icon" aria-hidden="true">▾</span>
				</button>
				<p class="section-sidebar-kicker">{currentSection.title}</p>
				<nav>
					<NavTree items={currentSection.pages} {currentUrl} />
					{#each currentSection.groups ?? [] as group (group.title)}
						<p class="section-sidebar-group">{group.title}</p>
						{#each group.pages as item (item.url)}
							<a href={item.url} aria-current={item.url === currentUrl ? 'page' : undefined}>
								{item.title}
							</a>
						{/each}
					{/each}
				</nav>
			</aside>
			<main class="content">
				{@render children()}
			</main>
		</div>
	{:else}
		<main class="content">
			{@render children()}
		</main>
	{/if}

	<footer class="site-footer">
		<nav class="site-footer-links" aria-label="Footer">
			<a href="https://basically.website/policies/privacy-policy" target="_blank" rel="noopener">Privacy Policy</a>
			<a href="https://basically.website/policies/terms-of-service" target="_blank" rel="noopener">Terms of Service</a>
			<a href="mailto:contact@basically.website">contact@basically.website</a>
			<a href="https://basically.website/?updates=1" target="_blank" rel="noopener">Get updates&nbsp;↗</a>
			<a href="https://discord.gg/6PZtqkwtaS" target="_blank" rel="noopener">Discord</a>
			<a href="https://github.com/basicallysource/sorter-v2/tree/main/docs">Source&nbsp;(<code>docs/</code>)</a>
		</nav>
		<p class="site-footer-legal">
			© basically. All rights reserved. LEGO® is a trademark of the LEGO Group of companies which
			does not sponsor, authorize, or endorse this site.
		</p>
	</footer>
</div>
