<script lang="ts">
	import PartDetail from '$lib/components/PartDetail.svelte';
	import HardwareDetail from '$lib/components/HardwareDetail.svelte';
	import Seo from '$lib/components/Seo.svelte';
	import AlternativeBadge from '$lib/components/AlternativeBadge.svelte';
	import { colorStore } from '$lib/colors.svelte';
	import { layerStore } from '$lib/layers.svelte';
	import {
		SECTIONS,
		sectionQty,
		primaryColorId,
		hardwareImage,
		type PartVersion
	} from '$lib/filament';
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';

	// Standalone page for a single part — the shareable, unfurlable form of the
	// dashboard modal. Serves both halves of the manifest off the same URL: a
	// printed part renders PartDetail, an off-the-shelf one renders HardwareDetail,
	// each under the normal toolbar with a back link + breadcrumb so it reads as a
	// sub-page of the tab the part belongs to.
	let { data } = $props();
	const part = $derived(data.part);
	const hardware = $derived(data.hardware);

	// The section this part sits in on the dashboard — the breadcrumb context. A part
	// can appear in more than one; the first is enough to say "you're inside <group>".
	const section = $derived(part ? (SECTIONS.find((s) => sectionQty(part, s.id) > 0) ?? null) : null);

	// Hardware quantities depend on the configured build, same as everywhere else.
	const layers = $derived(layerStore.sizes.length);

	// The card image: a printed part's render, an off-the-shelf part's product photo.
	const ogImage = $derived(part ? part.render : (hardware ? hardwareImage(hardware)?.src : undefined));
	const title = $derived(part?.name ?? hardware?.name ?? '');
	const description = $derived(part?.description || hardware?.description || undefined);

	// Seed the preview to the shared colour choices + newest version, matching the
	// modal. Not URL-synced: the page URL is already the shareable thing.
	let colorId = $state('ash-gray');
	let version = $state<PartVersion | null>(null);
	let seededId: string | null = null;
	$effect(() => {
		if (part && part.id !== seededId) {
			seededId = part.id;
			colorId = primaryColorId(part, colorStore.roles) ?? 'ash-gray';
			version = part.versions?.[part.versions.length - 1] ?? null;
		}
	});
</script>

<Seo {title} {description} image={ogImage} type="article" />

<div class="mx-auto max-w-4xl px-4 py-6 sm:px-6">
	<!-- breadcrumb: back to the tab this part lives on, with its group for context -->
	<nav class="mb-3 flex flex-wrap items-center gap-1 text-sm text-text-muted">
		{#if hardware}
			<a href="/hardware" class="inline-flex items-center gap-1 hover:text-text">
				<ChevronLeft size={15} /> Hardware
			</a>
			{#if hardware.category}
				<ChevronRight size={13} class="opacity-60" />
				<span>{hardware.category}</span>
			{/if}
		{:else}
			<a href="/" class="inline-flex items-center gap-1 hover:text-text">
				<ChevronLeft size={15} /> 3D printed parts
			</a>
			{#if section}
				<ChevronRight size={13} class="opacity-60" />
				<span>{section.name}</span>
			{/if}
		{/if}
		<ChevronRight size={13} class="opacity-60" />
		<span class="text-text">{title}</span>
	</nav>

	<h1 class="mb-4 flex flex-wrap items-center gap-2 text-2xl font-bold text-text">
		{title}
		{#if hardware}<AlternativeBadge value={hardware.alternative} />{/if}
	</h1>

	<div class="setup-card-shell overflow-hidden border">
		{#if hardware}
			<HardwareDetail {hardware} {layers} />
		{:else if part}
			<PartDetail {part} bind:colorId bind:version variant="page" />
		{/if}
	</div>
</div>
