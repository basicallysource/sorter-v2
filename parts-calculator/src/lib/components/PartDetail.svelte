<script lang="ts">
	import ConflictNotice from '$lib/components/ConflictNotice.svelte';
	import StlViewer from '$lib/components/StlViewer.svelte';
	import IdStamp from '$lib/components/IdStamp.svelte';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import DownloadButton from '$lib/components/DownloadButton.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import BuildPlates from '$lib/components/BuildPlates.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import ImageStrip from '$lib/components/ImageStrip.svelte';
	import { getBambuColor } from '$lib/bambu-colors';
	import { SITE_URL } from '$lib/seo';
	import { copyText } from '$lib/clipboard';
	import { duration, fmtDate, noteUrl, partOnshape, platesForPart, type Part, type PartCandidate, type PartVersion } from '$lib/filament';
	import { ExternalLink, FileText, FlaskConical, History, Image, Layers3, Share2, Check } from 'lucide-svelte';

	// The 3D-printed part detail view: the preview with the id-stamp controls laid
	// over it, then the facts, the download, and the history. Rendered two ways off
	// the SAME markup -- inside the parts dashboard / assembly modals
	// (`variant="modal"`, internal scroll under a pinned viewer) and as the
	// standalone `/part/<id>` page (`variant="page"`, natural flow). `colorId` /
	// `version` are controlled by the opener, which seeds them on show.
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

	// A candidate under test, picked from its strip; picking a version clears it.
	let candidate = $state<PartCandidate | null>(null);
	$effect(() => {
		part.id;
		candidate = null;
	});

	// The id stamp. The current part and every candidate come with pre-cut
	// downloads carrying their uid on one face each, best face first
	// (catalog/engrave.py); an older version has none. Two bits of state, shared
	// by the controls on the viewer and the checkbox at the download: whether
	// the download is stamped at all (on by default -- a traceable print is the
	// point) and which face. Both reset when the thing being viewed changes.
	const stamps = $derived(
		(candidate ? candidate.stamped : !version || version.version === part.version ? part.stamped : []) ?? []
	);
	let stampOn = $state(true);
	let faceIdx = $state(0);
	$effect(() => {
		part.id;
		candidate;
		version;
		faceIdx = 0;
	});
	const stamp = $derived(stampOn ? (stamps[faceIdx] ?? null) : null);
	let viewer: StlViewer | undefined = $state();

	// Every face's STL is fetched as soon as the part is shown, so flipping
	// through them swaps instantly out of the browser cache (they are served
	// immutable) instead of loading on each arrow press.
	$effect(() => {
		for (const s of stamps) fetch(s.stl).then((r) => r.arrayBuffer()).catch(() => {});
	});
	function onKey(e: KeyboardEvent) {
		if (!stampOn || stamps.length < 2 || e.metaKey || e.ctrlKey || e.altKey) return;
		const t = e.target as HTMLElement | null;
		if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
		if (e.key === 'ArrowRight') faceIdx = (faceIdx + 1) % stamps.length;
		else if (e.key === 'ArrowLeft') faceIdx = (faceIdx - 1 + stamps.length) % stamps.length;
		else return;
		e.preventDefault();
	}

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

<svelte:window onkeydown={onKey} />

<ConflictNotice conflicts={part.conflicts} />

{#key part.id}
	{@const vers = [...(part.versions ?? [])].reverse()}
	{@const active = version ?? part.versions?.[part.versions.length - 1] ?? null}
	{@const activeStl = stamp?.stl ?? candidate?.stl ?? active?.stl ?? part.stl}
	{@const isCurrent = !candidate && (!active || active.version === part.version)}
	{@const cands = part.candidates ?? []}
	{@const os = partOnshape(part)}
	{@const pid = part.id}
	{@const plates = platesForPart(pid)}
	{@const grams = candidate ? candidate.grams : (active?.grams ?? part.grams)}
	{@const seconds = candidate ? candidate.print_seconds : part.print_seconds}
	{@const onshapeHref = candidate?.onshape_version ?? os.version}
	{@const noteId = candidate?.note ?? active?.note ?? part.note}

	<!-- the preview, with the id-stamp controls and the colour picker laid over it -->
	<div class="relative {variant === 'modal' ? 'shrink-0' : ''}">
		<StlViewer bind:this={viewer} url={activeStl} color={getBambuColor(colorId).hex} mark={stamp} heightClass={variant === 'modal' ? 'h-[56vh]' : 'h-[60vh]'} />
		<div class="pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-start justify-between gap-2">
			<IdStamp where="viewport" uid={candidate?.uid ?? part.uid} {stamps} bind:on={stampOn} bind:faceIdx onView={() => viewer?.viewMark()} onReset={() => viewer?.resetView()} />
			<div class="pointer-events-auto ml-auto w-48 border border-border bg-[var(--color-surface)]/95 px-2.5 py-1.5 shadow-sm backdrop-blur"><ColorPicker bind:value={colorId} label="Preview color" /></div>
		</div>
	</div>

	<!-- in the modal the details scroll independently of the pinned viewer (which
	     owns wheel = zoom); on the page everything just flows -->
	<div class="{variant === 'modal' ? 'min-h-0 flex-1 overflow-y-auto' : ''} border-t border-border">
		<div class="px-5 py-4">
			<div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
				<div class="min-w-0 flex-1 space-y-2 text-sm">
					{#if candidate}
						<div class="inline-flex items-center gap-1.5 border border-border px-2 py-0.5 text-xs text-text-muted"><FlaskConical size={12} /> Candidate <span class="font-mono font-semibold text-text">{candidate.uid}</span>{#if candidate.name} · {candidate.name}{/if}</div>
						<p class="text-text">{candidate.message}</p>
					{:else}
						{#if part.description}<p class="text-text">{part.description}</p>{/if}
					{/if}
					{#if part.attributes?.length}
						<div class="flex flex-wrap gap-1.5">
							{#each part.attributes as a}<span class="border border-border bg-[var(--color-bg)] px-1.5 py-0.5 text-xs text-text-muted">{a.label}: <span class="text-text">{a.value}</span></span>{/each}
						</div>
					{/if}
					{#if noteId}
						<a class="inline-flex items-center gap-1 text-xs text-primary hover:text-primary-hover" href={noteUrl(noteId)} target="_blank" rel="noopener" title="A permanent write-up of something that happened to this part">
							<FileText size={12} /> Engineering note {noteId}
						</a>
					{/if}
				</div>
				<div class="flex shrink-0 flex-col items-start gap-2 sm:items-end">
					<DownloadButton href={activeStl} size="md" label={candidate ? `Download STL (candidate ${candidate.uid})` : isCurrent ? 'Download STL' : `Download STL (v${active?.version})`} />
					<div class="flex items-center gap-1.5"><IdStamp where="download" uid={candidate?.uid ?? part.uid} {stamps} bind:on={stampOn} bind:faceIdx /></div>
					<div class="flex items-center gap-3 text-xs">
						<button type="button" onclick={share} class="inline-flex items-center gap-1 {copied ? 'text-success' : 'text-primary hover:text-primary-hover'}" title="Copy a shareable link to this part's page">
							{#if copied}<Check size={13} /> Copied{:else}<Share2 size={13} /> Share{/if}
						</button>
						{#if onshapeHref}<a href={onshapeHref} target="_blank" rel="noopener" class="inline-flex items-center gap-0.5 text-primary hover:text-primary-hover">OnShape <ExternalLink size={11} /></a>{/if}
					</div>
				</div>
			</div>

			<dl class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
				{#snippet tile(label: string, value: string)}
					<div class="border border-border bg-[var(--color-bg)] px-3 py-2">
						<dt class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">{label}</dt>
						<dd class="mt-0.5 text-sm font-medium text-text">{value}</dd>
					</div>
				{/snippet}
				{#if candidate}
					{@render tile('Status', candidate.rejected_at ? `Rejected ${fmtDate(candidate.rejected_at)}` : candidate.superseded_by ? `Superseded by ${candidate.superseded_by}` : 'Under test')}
					{@render tile('Added', fmtDate(candidate.created_at))}
				{:else}
					{@render tile('Version', `v${active?.version ?? part.version}${isCurrent ? ' · current' : ''}`)}
					{@render tile(isCurrent ? 'Updated' : 'Dated', fmtDate(active?.date ?? part.updated_at))}
				{/if}
				{@render tile('Filament', grams != null ? `${grams.toFixed(0)} g` : '—')}
				{@render tile('Print time', seconds != null ? duration(seconds) : '—')}
			</dl>

			<div class="mt-3 space-y-2">
				<ChangeStatus kind="parts" id={part.id} name={part.name} />
				{#if part.low_tolerance}
					<Callout variant="info" title="Low tolerance — test print suggested">{part.low_tolerance_note ?? 'This part has little room for dimensional error. Print one first and confirm the fit before committing to the full set.'}</Callout>
				{/if}
				{#if candidate?.superseded_by}<p class="text-xs text-text-muted">Superseded by <span class="font-mono">{candidate.superseded_by}</span>{#if candidate.superseded_at} on {fmtDate(candidate.superseded_at)}{/if}.</p>{/if}
				{#if candidate}<p class="text-xs italic text-text-muted/70">Viewing a candidate. It is not the current part and is not counted in the build.</p>{/if}
				{#if !candidate && !isCurrent}<p class="text-xs italic text-text-muted/70">Viewing an older version for reference. Build from the current version unless you specifically need this one.</p>{/if}
			</div>

			{#if candidate?.images?.length || (!candidate && part.images?.length)}
				<div class="mt-4">
					<div class="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted"><Image size={12} /> Images</div>
					<ImageStrip images={(candidate ? candidate.images : part.images) ?? []} />
				</div>
			{/if}
			{#if plates.length}
				<div class="mt-4">
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

		{#if vers.length > 1}
			<div class="border-t border-border px-5 py-4">
				<h3 class="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted"><History size={12} /> Version history</h3>
				<div class="flex gap-2 overflow-x-auto pb-1">
					{#each vers as v (v.version)}
						{@const sel = !candidate && active?.version === v.version}
						<button type="button" onclick={() => { version = v; candidate = null; }} class="flex w-32 shrink-0 flex-col border {sel ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-primary/60'} bg-[var(--color-bg)] p-1.5 text-left" aria-pressed={sel}>
							<span class="mb-1 flex h-20 items-center justify-center border border-border bg-[var(--color-bg)]">
								{#if v.render}<img src={v.render} alt="v{v.version} preview" class="h-full w-full object-contain" />{:else}<span class="text-xs text-text-muted">no preview</span>{/if}
							</span>
							<span class="flex items-center gap-1 text-xs font-semibold text-text">v{v.version}{#if v.version === part.version}<span class="text-[10px] font-normal text-text-muted">current</span>{/if}</span>
							<span class="text-[11px] text-text-muted">{fmtDate(v.date)}{#if v.grams != null} · {v.grams.toFixed(0)} g{/if}</span>
						</button>
					{/each}
				</div>
				{#if active && !candidate}
					<div class="mt-2 border-t border-border pt-2 text-sm">
						<div class="font-medium text-text">v{active.version} · {fmtDate(active.date)}</div>
						<p class="mt-0.5 text-text-muted">{active.message}</p>
						{#if active.images?.length}<div class="mt-2"><ImageStrip images={active.images} /></div>{/if}
					</div>
				{/if}
			</div>
		{/if}
		{#if cands.length}
			<div class="border-t border-border px-5 py-4">
				<h3 class="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted"><FlaskConical size={12} /> Candidates</h3>
				<p class="mb-2 text-xs text-text-muted">Revisions under test for this part. Not part of the build — print one only to test it. Each carries its own id, so a test print stays identifiable.</p>
				<div class="flex gap-2 overflow-x-auto pb-1">
					{#each cands as c (c.uid)}
						{@const sel = candidate?.uid === c.uid}
						{@const retired = !!(c.superseded_by || c.rejected_at)}
						<button type="button" onclick={() => (candidate = sel ? null : c)} class="flex w-32 shrink-0 flex-col border {sel ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-primary/60'} bg-[var(--color-bg)] p-1.5 text-left {retired ? 'opacity-60' : ''}" aria-pressed={sel}>
							<span class="mb-1 flex h-20 items-center justify-center border border-border bg-[var(--color-bg)]">
								{#if c.render}<img src={c.render} alt="candidate {c.uid} preview" class="h-full w-full object-contain" />{:else}<span class="text-xs text-text-muted">no preview</span>{/if}
							</span>
							<span class="flex items-center gap-1 font-mono text-xs font-semibold text-text">{c.uid}{#if retired}<span class="font-sans text-[10px] font-normal text-text-muted">{c.rejected_at ? 'rejected' : 'superseded'}</span>{/if}</span>
							<span class="text-[11px] text-text-muted">{fmtDate(c.created_at)}{#if c.grams != null} · {c.grams.toFixed(0)} g{/if}</span>
						</button>
					{/each}
				</div>
			</div>
		{/if}
	</div>

	<Modal bind:open={platesOpen} title="Build plates · {part.name}">
		<div class="p-4">
			<BuildPlates highlightPartId={pid} />
		</div>
	</Modal>
{/key}
