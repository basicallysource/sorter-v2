<script lang="ts">
	import StlViewer from '$lib/components/StlViewer.svelte';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import DownloadButton from '$lib/components/DownloadButton.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import BuildPlates from '$lib/components/BuildPlates.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import { getBambuColor } from '$lib/bambu-colors';
	import { SITE_URL } from '$lib/seo';
	import { copyText } from '$lib/clipboard';
	import { duration, fmtDate, partOnshape, platesForPart, type Part, type PartVersion } from '$lib/filament';
	import { ExternalLink, History, Layers3, Share2, Check } from 'lucide-svelte';

	// The 3D-printed part detail view: 3D viewer, specs, download/share, build plates
	// and version history. Rendered two ways off the SAME markup — inside the parts
	// dashboard / assembly modals (`variant="modal"`, internal scroll under a pinned
	// viewer) and as the standalone `/part/<id>` page (`variant="page"`, natural flow).
	// `colorId` / `version` are controlled by the opener, which seeds them on show.
	let {
		part,
		colorId = $bindable('ash-gray'),
		version = $bindable<PartVersion | null>(null),
		variant = 'modal'
	}: {
		part: Part;
		colorId?: string;
		version?: PartVersion | null;
		variant?: 'modal' | 'page';
	} = $props();

	// A part's own build-plate popup, opened from the "view" link on a plate card.
	let platesOpen = $state(false);

	// Share = the part's permanent /part/<id> page, which unfurls with the part's own
	// image + name. A query-param deep link can't do that on a static site (crawlers
	// don't run JS and every ?part=… serves the same prerendered index.html).
	let copied = $state(false);
	let copyTimer: ReturnType<typeof setTimeout> | undefined;
	async function share() {
		if (await copyText(`${SITE_URL}/part/${part.id}`)) {
			copied = true;
			clearTimeout(copyTimer);
			copyTimer = setTimeout(() => (copied = false), 1800);
		}
	}
</script>

{#key part.id}
	{@const vers = [...(part.versions ?? [])].reverse()}
	{@const active = version ?? part.versions?.[part.versions.length - 1] ?? null}
	{@const activeStl = active?.stl ?? part.stl}
	{@const isCurrent = !active || active.version === part.version}
	{@const os = partOnshape(part)}
	{@const pid = part.id}
	{@const plates = platesForPart(pid)}
	<div class={variant === 'modal' ? 'shrink-0' : ''}>
		{#key activeStl}
			<StlViewer url={activeStl} color={getBambuColor(colorId).hex} />
		{/key}
	</div>
	<!-- in the modal the details scroll independently of the pinned 3D viewer (which
	     owns wheel = zoom); on the page everything just flows -->
	<div class={variant === 'modal' ? 'min-h-0 flex-1 overflow-y-auto' : ''}>
		<div class="grid gap-4 px-4 py-3 sm:grid-cols-[1fr_auto]">
			<div class="min-w-0 space-y-2 text-sm">
				{#if part.description}<p class="text-text-muted">{part.description}</p>{/if}
				{#if part.attributes?.length}
					<div class="flex flex-wrap gap-1.5">
						{#each part.attributes as a}<span class="border border-border bg-[var(--color-bg)] px-1.5 py-0.5 text-xs text-text-muted">{a.label}: <span class="text-text">{a.value}</span></span>{/each}
					</div>
				{/if}
				<dl class="grid max-w-sm grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-text-muted">
					<dt>Version</dt><dd class="text-text">v{active?.version ?? part.version}{isCurrent ? ' (current)' : ''}</dd>
					<dt>{isCurrent ? 'Updated' : 'Dated'}</dt><dd class="text-text">{fmtDate(active?.date ?? part.updated_at)}</dd>
					{#if active?.grams != null}<dt>Filament</dt><dd class="text-text">{active.grams.toFixed(0)} g</dd>{/if}
					<dt>Print time</dt><dd class="text-text">{duration(part.print_seconds)}</dd>
				</dl>
				<div><ChangeStatus kind="parts" id={part.id} name={part.name} /></div>
				{#if part.low_tolerance}
					<Callout variant="info" title="Low tolerance — test print suggested">{part.low_tolerance_note ?? 'This part has little room for dimensional error. Print one first and confirm the fit before committing to the full set.'}</Callout>
				{/if}
				<div class="flex flex-wrap items-center gap-3 pt-1">
					<DownloadButton href={activeStl} size="md" label={isCurrent ? 'Download STL' : `Download STL (v${active?.version})`} />
					<button type="button" onclick={share} class="inline-flex items-center gap-1 text-xs {copied ? 'text-success' : 'text-primary hover:text-primary-hover'}" title="Copy a shareable link to this part's page">
						{#if copied}<Check size={13} /> Copied{:else}<Share2 size={13} /> Share{/if}
					</button>
					{#if os.version}<a href={os.version} target="_blank" rel="noopener" class="inline-flex items-center gap-0.5 text-xs text-primary hover:text-primary-hover">OnShape <ExternalLink size={11} /></a>{/if}
				</div>
				{#if plates.length}
					<div class="pt-1">
						<div class="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted"><Layers3 size={12} /> On build plates</div>
						<div class="flex gap-2 overflow-x-auto pb-1">
							{#each plates as pl (pl.id)}
								<div class="flex w-56 shrink-0 flex-col border border-border bg-[var(--color-bg)] p-2">
									<div class="mb-1.5 flex gap-1 overflow-x-auto">
										{#each pl.thumbs as t}<img src={t} alt="{pl.name} preview" class="h-20 w-20 shrink-0 border border-border bg-[var(--color-surface)] object-contain" />{/each}
									</div>
									<div class="mb-2 flex flex-wrap gap-1">
										{#each pl.parts as pp}<span class="border px-1 py-0.5 text-[11px] {pp.part_id === pid ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-muted'}">{pp.count}× {pp.name}</span>{/each}
									</div>
									<div class="mt-auto flex items-center gap-2">
										<span class="min-w-0 flex-1 truncate text-xs font-medium text-text" title={pl.name}>{pl.name}</span>
										<button type="button" class="shrink-0 text-xs text-primary hover:text-primary-hover" onclick={() => (platesOpen = true)}>view</button>
										<DownloadButton href={pl.download} size="sm" label="3mf" title="Download {pl.name}.3mf" />
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
			<div class="w-44 shrink-0">
				<ColorPicker bind:value={colorId} label="Preview color" />
			</div>
		</div>
		{#if vers.length > 1}
			<div class="border-t border-border px-4 py-3">
				<h3 class="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted"><History size={12} /> Version history</h3>
				<div class="flex gap-2 overflow-x-auto pb-1">
					{#each vers as v (v.version)}
						{@const sel = active?.version === v.version}
						<button type="button" onclick={() => (version = v)} class="flex w-32 shrink-0 flex-col border {sel ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-primary/60'} bg-[var(--color-bg)] p-1.5 text-left" aria-pressed={sel}>
							<span class="mb-1 flex h-20 items-center justify-center border border-border bg-[var(--color-bg)]">
								{#if v.render}<img src={v.render} alt="v{v.version} preview" class="h-full w-full object-contain" />{:else}<span class="text-xs text-text-muted">no preview</span>{/if}
							</span>
							<span class="flex items-center gap-1 text-xs font-semibold text-text">v{v.version}{#if v.version === part.version}<span class="text-[10px] font-normal text-text-muted">current</span>{/if}</span>
							<span class="text-[11px] text-text-muted">{fmtDate(v.date)}{#if v.grams != null} · {v.grams.toFixed(0)} g{/if}</span>
						</button>
					{/each}
				</div>
				{#if active}
					<div class="mt-2 border-t border-border pt-2 text-sm">
						<div class="font-medium text-text">v{active.version} · {fmtDate(active.date)}</div>
						<p class="mt-0.5 text-text-muted">{active.message}</p>
						{#if !isCurrent}<p class="mt-1 text-xs italic text-text-muted/70">Viewing an older version for reference. Build from the current version unless you specifically need this one.</p>{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<Modal bind:open={platesOpen} title="Build plates · {part.name}">
		<div class="p-4">
			<BuildPlates highlightPartId={pid} />
		</div>
	</Modal>
{/key}
