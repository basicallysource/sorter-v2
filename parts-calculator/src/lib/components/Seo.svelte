<script lang="ts">
	import { page } from '$app/state';
	import { SITE_NAME, DEFAULT_DESCRIPTION, absUrl, pageTitle } from '$lib/seo';

	// One place that emits every head tag a link preview needs. Each route renders
	// <Seo …/> with whatever it knows about the page; anything omitted falls back to
	// the site defaults, so every page still ships a complete, crawlable card.
	// `image` has no default: pages without a meaningful image ship a text-only card
	// rather than a shared placeholder hero (see $lib/seo).
	let {
		title,
		description = DEFAULT_DESCRIPTION,
		image,
		type = 'website'
	}: {
		title?: string;
		description?: string;
		image?: string;
		type?: string;
	} = $props();

	const fullTitle = $derived(pageTitle(title));
	// pathname (not href): the canonical URL never carries the modal's ?part=… state
	const canonical = $derived(absUrl(page.url.pathname));
	const ogImage = $derived(image ? absUrl(image) : undefined);
</script>

<svelte:head>
	<title>{fullTitle}</title>
	<meta name="description" content={description} />
	<link rel="canonical" href={canonical} />

	<meta property="og:site_name" content={SITE_NAME} />
	<meta property="og:title" content={fullTitle} />
	<meta property="og:description" content={description} />
	<meta property="og:type" content={type} />
	<meta property="og:url" content={canonical} />
	{#if ogImage}
		<meta property="og:image" content={ogImage} />
	{/if}

	<meta name="twitter:card" content={ogImage ? 'summary_large_image' : 'summary'} />
	<meta name="twitter:title" content={fullTitle} />
	<meta name="twitter:description" content={description} />
	{#if ogImage}
		<meta name="twitter:image" content={ogImage} />
	{/if}
</svelte:head>
