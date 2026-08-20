<script lang="ts">
	import {
		PARTS,
		SECTIONS,
		ASSEMBLIES,
		CHANGES,
		COLOR_ROLES,
		SETTINGS,
		STORE_URL,
		categoryMultiplier,
		sectionQty,
		getAssembly,
		getFolder,
		partSwatches,
		primaryColorId,
		machineColorUnits,
		effectiveGrams,
		displayCount,
		machineQty,
		buyList,
		grams,
		money,
		duration,
		durationLong,
		fmtDate,
		commitUrl,
		partOnshape,
		PLATES,
		platesForPart,
		type Part,
		type PartVersion
	} from '$lib/filament';
	import { getBambuColor } from '$lib/bambu-colors';
	import { partsCsv } from '$lib/parts-csv';
	import { download, exportSpec, filename } from '$lib/csv';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PartDetailModal from '$lib/components/PartDetailModal.svelte';
	import BuildPlates from '$lib/components/BuildPlates.svelte';
	import Seo from '$lib/components/Seo.svelte';
	import { zipSync } from 'fflate';
	import { onMount } from 'svelte';
	import { loadConfig, saveConfig, clearConfig } from '$lib/config';
	import { layerStore, addLayer as addLayerStore, removeLayerAt, setSize, setSizes } from '$lib/layers.svelte';
	import { colorStore, defaultRoleColors, resetRoleColors } from '$lib/colors.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import MissingImage from '$lib/components/MissingImage.svelte';
	import { Download, Package, ZoomIn, Loader, Info, Plus, X, RotateCcw, Clock, Layers3, ExternalLink, AlertTriangle, History, ChevronRight, ChevronDown } from 'lucide-svelte';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { browser } from '$app/environment';

	// ---- defaults (also used by "reset to default") -----------------------------
	const defaultFunnelSizes = (): ('third' | 'half')[] => ['third', 'third', 'half'];
	const defaultSelected = () =>
		Object.fromEntries(PARTS.map((p) => [p.id, !('bins' in p.quantities)]));
	// only parts that *opt into* support (support_intentional) expose the toggle; they
	// default to counting their support. Parts the slicer auto-forced support on are
	// left out entirely — no toggle, no support in the totals.
	const defaultInclSupport = () =>
		Object.fromEntries(PARTS.filter((p) => p.support_intentional).map((p) => [p.id, true]));

	// per-layer size list is the shared source of truth (also used by the framing tab)
	const funnelSizes = $derived(layerStore.sizes);
	const layers = $derived(funnelSizes.length);
	function addLayer() {
		addLayerStore();
	}
	function removeLayer(i: number) {
		removeLayerAt(i);
	}
	// colours live in the shared store so the assembly tab sees the same choices
	const roleColors = $derived(colorStore.roles);
	let selected = $state<Record<string, boolean>>(defaultSelected());
	let surplus = $state(15);
	let printBins = $state(false); // top-level: print bins or not (auto-selects the right bins)
	const partsById = new Map(PARTS.map((p) => [p.id, p]));
	// bins are governed by the printBins toggle (+ per-layer size); everything else by its checkbox
	function isIncluded(id: string): boolean {
		const p = partsById.get(id);
		if (p && 'bins' in p.quantities) return printBins;
		return selected[id];
	}
	// include each part's support material in totals — default on for the stator only
	let inclSupport = $state<Record<string, boolean>>(defaultInclSupport());
	// support counts only for parts that intentionally opt into it, never auto-forced ones
	const supportOn = (id: string): boolean => !!partsById.get(id)?.support_intentional && !!inclSupport[id];

	// ---- persistence: load saved config at boot, save on change ----------------
	let configLoaded = $state(false);
	onMount(() => {
		const c = loadConfig();
		if (c) {
			// roleColors is not read here — colors.svelte owns it (and migrates the old blob)
			if (typeof c.printBins === 'boolean') printBins = c.printBins;
			if (typeof c.surplus === 'number') surplus = c.surplus;
			if (c.selected) selected = { ...selected, ...c.selected };
			if (c.inclSupport) inclSupport = { ...inclSupport, ...c.inclSupport };
		}
		configLoaded = true;

		// deep link: open a part's detail modal (with an optional preview colour and
		// version) straight from the URL, so a view can be shared. Query params only
		// exist in the browser — the site is prerendered — hence reading here.
		const sp = page.url.searchParams;
		const pid = sp.get('part');
		const p = pid ? partsById.get(pid) : undefined;
		if (p) {
			const c = sp.get('color');
			const v = sp.get('v');
			openViewer(p, {
				color: c && getBambuColor(c).id === c ? c : undefined,
				version: v ? p.versions?.find((x) => String(x.version) === v) : undefined
			});
		}
		urlReady = true;
	});

	// Mirror the open part + its preview colour/version into the URL so the current
	// view is a shareable link. Colour and version are only written when they differ
	// from the part's defaults, keeping shared links clean. This is deliberately not
	// persisted to localStorage — it's about sharing a link, not restoring a session.
	$effect(() => {
		if (!browser || !urlReady) return;
		const params = new URLSearchParams(page.url.search);
		if (viewerOpen && viewerPart) {
			params.set('part', viewerPart.id);
			const defColor = primaryColorId(viewerPart, roleColors) ?? 'ash-gray';
			if (viewerColor && viewerColor !== defColor) params.set('color', viewerColor);
			else params.delete('color');
			const newest = viewerPart.versions?.[viewerPart.versions.length - 1]?.version;
			if (viewerVersion && viewerVersion.version !== newest) params.set('v', String(viewerVersion.version));
			else params.delete('v');
		} else {
			params.delete('part');
			params.delete('color');
			params.delete('v');
		}
		const qs = params.toString();
		const target = qs ? `${location.pathname}?${qs}` : location.pathname;
		if (target !== location.pathname + location.search) replaceState(target, {});
	});
	$effect(() => {
		const snapshot = { printBins, surplus, selected, inclSupport };
		if (configLoaded) saveConfig($state.snapshot(snapshot));
	});
	function resetToDefaults() {
		setSizes(defaultFunnelSizes());
		resetRoleColors();
		selected = defaultSelected();
		inclSupport = defaultInclSupport();
		surplus = 15;
		printBins = false;
		clearConfig();
	}
	let zipping = $state(false);
	let activeTab = $state<'parts' | 'plates'>('parts');
	let platesModalOpen = $state(false);
	let platesModalPartId = $state<string | null>(null);
	function openPlatesModal(id: string) {
		platesModalPartId = id;
		platesModalOpen = true;
	}
	let viewerOpen = $state(false);
	let viewerPart = $state<Part | null>(null);
	// the detail modal is controlled here so its state can be mirrored into the URL
	// (making a specific part / preview colour / version a shareable link). Seeded on
	// open; the modal binds and writes back to these.
	let viewerColor = $state('ash-gray');
	let viewerVersion = $state<PartVersion | null>(null);
	// gate URL writes until the initial deep-link read has run (see onMount), so we
	// never clobber ?part=… before we've had a chance to open it
	let urlReady = $state(false);

	// the per-layer size drives both the funnel and the bin set for that layer
	function variantCount(id: string): number | null {
		const nThird = funnelSizes.filter((s) => s === 'third').length;
		const nHalf = funnelSizes.filter((s) => s === 'half').length;
		switch (id) {
			case 'funnel-third': return nThird;
			case 'funnel-half': return nHalf;
			case 'bin-half-left':
			case 'bin-half-right': return nHalf * 6; // 6 per section, 6 sections, per half layer
			case 'bin-third-left':
			case 'bin-third-center':
			case 'bin-third-rightback': return nThird * 6; // 18 per third layer (3 × 6)
			default: return null;
		}
	}

	// per-layer size 'half' = 12 bins, 'third' = 18 bins
	const sizePreview = {
		half: { count: 12, bins: ['bin-half-left', 'bin-half-right'], funnel: 'funnel-half' },
		third: { count: 18, bins: ['bin-third-left', 'bin-third-center', 'bin-third-rightback'], funnel: 'funnel-third' }
	} as const;
	function render(id: string): string {
		return partsById.get(id)?.render ?? '';
	}

	const buy = $derived(
		buyList(layers, roleColors, isIncluded, supportOn, variantCount, surplus)
	);

	// theoretical total print time: every included part printed alone, sequentially,
	// on one printer (one part per plate — no batching)
	const totalPrintSeconds = $derived(
		PARTS.reduce((sum, p) => {
			if (!isIncluded(p.id)) return sum;
			const vc = variantCount(p.id);
			const count = vc !== null ? vc : machineQty(p, layers);
			return sum + p.print_seconds * count;
		}, 0)
	);

	const sectionRows = $derived(
		SECTIONS.map((s) => {
			const parts = PARTS.filter((p) => sectionQty(p, s.id) > 0);
			const mult = categoryMultiplier(s.id, layers);
			const selectedGrams = parts
				.filter((p) => isIncluded(p.id))
				.reduce(
					(sum, p) => sum + effectiveGrams(p, supportOn(p.id)) * displayCount(p, s.id, layers, variantCount),
					0
				);
			return { section: s, parts, mult, selectedGrams };
		}).filter((r) => r.parts.length > 0)
	);

	const selectedParts = $derived(PARTS.filter((p) => isIncluded(p.id)));

	// CSV of what's selected: quantities, real sliced weights, resolved colours,
	// and the permanent STL link, so the file is enough to print from.
	function downloadCsv() {
		const spec = exportSpec(layers);
		const parts = selectedParts.length ? selectedParts : PARTS;
		download(
			filename(spec, 'printed-parts'),
			partsCsv(parts, spec, {
				grams: (p) => effectiveGrams(p, supportOn(p.id)),
				colors: (p) =>
					machineColorUnits(p, layers, roleColors).map((u) => ({
						name: u.colorId ? (getBambuColor(u.colorId)?.name ?? u.colorId) : 'any',
						qty: u.count,
						sections: u.sections
					})),
				onshape: (p) => partOnshape(p).version ?? partOnshape(p).doc
			})
		);
	}
	const allSelected = $derived(PARTS.every((p) => selected[p.id]));

	const prettyPattern = SETTINGS.infill_pattern.replace('adaptivecubic', 'adaptive cubic');
	const settingsRows: [string, string][] = [
		['Printer', 'Bambu Lab A1 · 0.4 mm'],
		['Layer height', '0.20 mm'],
		['Infill', `${SETTINGS.infill_density} ${prettyPattern}`],
		['Supports', `Off (per part; stator: normal ≤${SETTINGS.support_threshold_deg}°)`],
		['Skirt', 'None'],
		['Filament', `${SETTINGS.filament} · ${SETTINGS.density_g_cm3} g/cm³`]
	];

	function setAll(v: boolean) {
		selected = Object.fromEntries(PARTS.map((p) => [p.id, v]));
	}

	type Block =
		| { kind: 'part'; part: Part }
		| { kind: 'group'; groupKind: 'assembly' | 'folder'; id: string; parts: Part[] };
	function groupBlocks(parts: Part[], sectionId: string): Block[] {
		const blocks: Block[] = [];
		const represented = new Set<string>();
		let cur: Extract<Block, { kind: 'group' }> | null = null;
		for (const p of parts) {
			const groupKind = p.folder ? 'folder' : p.assembly ? 'assembly' : null;
			const groupId = p.folder ?? p.assembly;
			if (groupKind && groupId) {
				if (groupKind === 'assembly') represented.add(groupId);
				if (!cur || cur.id !== groupId || cur.groupKind !== groupKind) {
					cur = { kind: 'group', groupKind, id: groupId, parts: [] };
					blocks.push(cur);
				}
				cur.parts.push(p);
			} else {
				cur = null;
				blocks.push({ kind: 'part', part: p });
			}
		}
		for (const assembly of ASSEMBLIES) {
			if (assembly.section === sectionId && assembly.status === 'stub' && !represented.has(assembly.id)) {
				blocks.push({ kind: 'group', groupKind: 'assembly', id: assembly.id, parts: [] });
			}
		}
		return blocks;
	}
	// Assemblies collapse to a single rollup row carrying the part count and the
	// summed grams; expanding reveals the individual parts underneath.
	let expandedAsm = $state<Record<string, boolean>>({});
	const asmKey = (sectionId: string, id: string) => `${sectionId}:${id}`;
	function toggleAsm(k: string) {
		expandedAsm[k] = !expandedAsm[k];
	}
	function asmGrams(parts: Part[], sectionId: string): number {
		return parts.reduce(
			(sum, p) =>
				sum +
				(isIncluded(p.id)
					? effectiveGrams(p, supportOn(p.id)) * displayCount(p, sectionId, layers, variantCount)
					: 0),
			0
		);
	}
	const asmAllOn = (parts: Part[]) => parts.every((p) => isIncluded(p.id));
	const asmSomeOn = (parts: Part[]) => parts.some((p) => isIncluded(p.id));
	// bins are governed by the Print bins toggle, so the rollup checkbox skips them
	function setAsm(parts: Part[], v: boolean) {
		for (const p of parts) if (!('bins' in p.quantities)) selected[p.id] = v;
	}

	function openViewer(p: Part, seed?: { color?: string; version?: PartVersion | null }) {
		viewerPart = p;
		viewerColor = seed?.color ?? primaryColorId(p, roleColors) ?? 'ash-gray';
		viewerVersion = seed?.version ?? p.versions?.[p.versions.length - 1] ?? null;
		viewerOpen = true;
	}
	// A click anywhere on a part row opens its detail modal — except on the row's
	// own interactive controls (checkbox, links, buttons, popovers).
	function rowClickToOpen(e: MouseEvent, p: Part) {
		if ((e.target as HTMLElement).closest('button, a, input, label, [role="tooltip"]')) return;
		openViewer(p);
	}
	async function downloadZip(parts: Part[], name: string) {
		if (!parts.length) return;
		zipping = true;
		try {
			const files: Record<string, Uint8Array> = {};
			for (const p of parts) {
				const res = await fetch(p.stl);
				files[`${p.id}.stl`] = new Uint8Array(await res.arrayBuffer());
			}
			const zipped = zipSync(files, { level: 6 });
			const a = document.createElement('a');
			a.href = URL.createObjectURL(new Blob([zipped as BlobPart], { type: 'application/zip' }));
			a.download = name;
			a.click();
			URL.revokeObjectURL(a.href);
		} finally {
			zipping = false;
		}
	}
</script>

<Seo />

<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6">
	<header class="mb-5">
		<h1 class="text-2xl font-bold text-text">3D printed parts</h1>
		<p class="mt-1 text-sm text-text-muted">
			Configure a build to get per-color filament quantities and download the STLs. Filament
			estimates from OrcaSlicer outputs.
		</p>
	</header>

	<!-- print settings -->
	<table class="pl-card pl-settings mb-6 max-w-xl">
		<tbody>
			{#each settingsRows as [k, v] (k)}
				<tr>
					<td class="pl-settings-k">{k}</td>
					<td class="pl-settings-v">{v}</td>
				</tr>
			{/each}
		</tbody>
	</table>

	<!-- BUILD OPTIONS = colors + layer configuration -->
	<section class="mb-8">
		<div class="mb-3 flex items-center justify-between">
			<h2 class="text-base font-semibold text-text">Build options</h2>
			<button
				class="inline-flex items-center gap-1.5 text-sm text-text-muted hover:text-text"
				onclick={resetToDefaults}
				title="Reset all build options to defaults"
			>
				<RotateCcw size={14} /> Reset to default
			</button>
		</div>

		<!-- colors -->
		<div class="setup-panel mb-4 p-4">
			<div class="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted">
				Colors
				<Popover width="w-72" label="About the color options">
					Each color picker sets every part in that group. Parts that must be a specific color —
					stators, rotors, light post caps, the classification dome, the lazy-Susan chute mount — keep
					their required color and aren't affected.
				</Popover>
			</div>
			<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
				{#each COLOR_ROLES as role (role.id)}
					<ColorPicker bind:value={colorStore.roles[role.id]} label={role.name} />
				{/each}
			</div>
		</div>

		<!-- layer configuration -->
		<div class="setup-panel p-4">
			<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
				<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
					Layers <span class="font-normal normal-case text-text-muted">· {layers} layer{layers === 1 ? '' : 's'}, bins per layer</span>
				</span>
				<label class="flex cursor-pointer items-center gap-2 text-sm">
					<input class="setup-toggle h-4 w-4" type="checkbox" bind:checked={printBins} />
					<span class="font-medium text-text">Print bins</span>
					<span class="text-xs text-text-muted">— include bins (size/qty per layer below)</span>
				</label>
			</div>
			<div class="flex flex-col gap-2">
				{#each funnelSizes as size, i (i)}
					{@const pv = sizePreview[size]}
					<div class="group setup-card-shell flex flex-wrap items-center gap-3 border px-3 py-2">
						<span class="w-16 shrink-0 text-sm font-medium text-text">Layer {i + 1}</span>
						<div class="flex">
							<button class="setup-button-secondary h-9 px-3 text-sm {size === 'half' ? 'setup-button-primary' : ''}" onclick={() => setSize(i, 'half')}>12 bins</button>
							<button class="setup-button-secondary h-9 border-l-0 px-3 text-sm {size === 'third' ? 'setup-button-primary' : ''}" onclick={() => setSize(i, 'third')}>18 bins</button>
						</div>
						<div class="ml-auto flex items-center gap-1.5">
							{#each pv.bins as b (b)}
								<img src={render(b)} alt={b} class="h-9 w-9 border border-border bg-[var(--color-bg)] object-contain {printBins ? '' : 'opacity-30'}" title={partsById.get(b)?.name} />
							{/each}
							<span class="px-1 text-text-muted">+</span>
							<img src={render(pv.funnel)} alt="funnel" class="h-9 w-9 border border-primary/40 bg-[var(--color-bg)] object-contain" title="{size} funnel" />
						</div>
						{#if layers > 1}
							<button
								class="flex h-7 w-7 shrink-0 items-center justify-center text-text-muted opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
								onclick={() => removeLayer(i)}
								aria-label="Remove layer {i + 1}"
								title="Remove layer"
							>
								<X size={16} />
							</button>
						{/if}
					</div>
				{/each}
				<button
					class="setup-button-secondary flex h-10 w-full items-center justify-center gap-1.5 text-sm font-medium"
					onclick={addLayer}
				>
					<Plus size={16} /> Add layer
				</button>
			</div>
		</div>
	</section>

	{#snippet partRow(p: Part, sectionId: string, indent: boolean)}
		{@const n = displayCount(p, sectionId, layers, variantCount)}
		{@const sw = partSwatches(p, sectionId, roleColors)}
		{@const eff = effectiveGrams(p, supportOn(p.id))}
		{@const os = partOnshape(p)}
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions a11y_click_events_have_key_events -->
		<tr class="pl-row group/row" class:pl-kid={indent} onclick={(e) => rowClickToOpen(e, p)} title="View {p.name} details">
			<td class="pl-c-check">
				{#if 'bins' in p.quantities}
					<input class="setup-toggle h-4 w-4" type="checkbox" checked={printBins} onchange={() => (printBins = !printBins)} aria-label="Print bins (set in Build options)" title="Controlled by the Print bins toggle in Build options" />
				{:else}
					<input class="setup-toggle h-4 w-4" type="checkbox" bind:checked={selected[p.id]} aria-label="Select {p.name}" />
				{/if}
			</td>
			<td class="pl-c-thumb">
				<button
					type="button"
					class="pl-thumb group relative"
					onclick={() => openViewer(p)}
					title="View {p.name} in 3D"
				>
					<img src={p.render} alt={p.name} />
					<span class="absolute inset-0 flex items-center justify-center bg-black/40 text-white opacity-0 transition-opacity group-hover:opacity-100 group-hover/row:opacity-100"><ZoomIn size={16} /></span>
				</button>
			</td>
			<td class="pl-c-name">
				<span class="pl-name">
					{p.name}
					{#if p.optional}<Badge variant="warning">Optional</Badge>{/if}
					{#if p.support_intentional}<Badge variant="info" title="Printed with support material — included in this part's grams">Supports</Badge>{/if}
						{#if platesForPart(p.id).length}<button type="button" class="inline-flex items-center gap-0.5 border border-border px-1 text-xs text-text-muted hover:border-primary hover:text-primary" onclick={() => openPlatesModal(p.id)} title="Show plates with this part"><Layers3 size={11} /> {platesForPart(p.id).length} plate{platesForPart(p.id).length === 1 ? '' : 's'}</button>{/if}{#if os.version}<a href={os.version} target="_blank" rel="noopener" class="inline-flex items-center gap-0.5 border border-border px-1 text-xs text-text-muted hover:border-primary hover:text-primary" title="Open the exact OnShape version this STL came from">OnShape <ExternalLink size={11} /></a>{/if}{#if p.info}<Popover width="w-64" label="About {p.name}" text={p.info} />{/if}<ChangeStatus kind="parts" id={p.id} name={p.name} />{#if p.low_tolerance}<Popover width="w-72" label="Fit notes for {p.name}">{#snippet trigger({ toggle, open })}<Badge as="button" variant="warning" onclick={toggle} aria-expanded={open}><AlertTriangle size={11} /> Tight fit</Badge>{/snippet}<b class="text-text">Low tolerance.</b> This part has little room for dimensional error, so a test print is worth doing before you commit to the full set.{#if p.low_tolerance_note}<span class="mt-2 block border-t border-border pt-2 text-text">{p.low_tolerance_note}</span>{/if}</Popover>{/if}{#if p.attributes?.length}{#each p.attributes as a}<span class="border border-border bg-[var(--color-bg)] px-1 text-xs text-text-muted" title={a.label}>{a.label}: <span class="text-text">{a.value}</span></span>{/each}{/if}{#if p.versions && p.versions.length > 1}<Popover width="w-80" label="Version history for {p.name}">{#snippet trigger({ toggle, open })}<button type="button" onclick={toggle} aria-expanded={open} class="inline-flex items-center gap-0.5 border border-border px-1 text-xs text-text-muted hover:border-primary hover:text-primary" title="Version history"><History size={11} /> v{p.version} · {p.versions?.length ?? 0} versions</button>{/snippet}<b class="text-text">Version history</b><ul class="mt-1 space-y-2">{#each [...(p.versions ?? [])].reverse() as v}<li class="border-t border-border pt-2 first:border-t-0 first:pt-0"><div class="flex items-center gap-1.5 text-text"><b>v{v.version}</b><span class="text-text-muted">· {fmtDate(v.date)}</span>{#if commitUrl(v.commit)}<a href={commitUrl(v.commit)} target="_blank" rel="noopener" class="ml-auto inline-flex items-center gap-0.5 text-primary hover:text-primary-hover">{v.commit} <ExternalLink size={10} /></a>{:else}<span class="ml-auto italic text-text-muted/70">uncommitted</span>{/if}</div><div class="mt-0.5">{v.message}</div>{#if v.onshape_version}<div class="mt-1"><a href={v.onshape_version} target="_blank" rel="noopener" class="inline-flex items-center gap-0.5 text-primary hover:text-primary-hover">OnShape <ExternalLink size={10} /></a></div>{/if}</li>{/each}</ul></Popover>{/if}
				</span>
				<span class="pl-meta">
					{#each sw as s}
						<span class="inline-flex items-center gap-1">
							<span class="pl-chip" style="background:{s.color?.hex ?? 'repeating-linear-gradient(45deg,#ccc,#ccc 2px,#eee 2px,#eee 4px)'}"></span>
							{#if sw.length > 1}{s.qty}× {/if}{s.color?.name ?? 'any'}
						</span>
					{/each}
					<span title="Print time for one {p.name}">· {duration(p.print_seconds)}</span>
				</span>
				{#if p.support_intentional}
					<label class="pl-support">
						<input class="setup-toggle h-3.5 w-3.5" type="checkbox" bind:checked={inclSupport[p.id]} />
						total {p.grams.toFixed(0)} g · support {p.support_grams.toFixed(0)} g
						<span class="opacity-70">({inclSupport[p.id] ? 'included' : 'excluded'})</span>
					</label>
				{/if}
			</td>
			<td class="pl-c-each">{eff.toFixed(0)} g × {n}</td>
			<td class="pl-c-total">{grams(eff * n)}</td>
			<td class="pl-c-dl">
				<a class="pl-dl" href={p.stl} download title="Download {p.name}.stl"><Download size={16} /></a>
			</td>
		</tr>
	{/snippet}

	<!-- min-w-0: a grid item defaults to min-width:auto, so the parts table would
	     push its own track wider than the page on a phone -->
	<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
		<!-- LEFT: parts by section -->
		<div class="min-w-0">
			<div class="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border">
				<div class="flex gap-1">
					<button class="border-b-2 px-3 py-2 text-sm font-semibold {activeTab === 'parts' ? 'border-text text-text' : 'border-transparent text-text-muted hover:text-text'}" onclick={() => (activeTab = 'parts')}>Parts</button>
					<button class="border-b-2 px-3 py-2 text-sm font-semibold {activeTab === 'plates' ? 'border-text text-text' : 'border-transparent text-text-muted hover:text-text'}" onclick={() => (activeTab = 'plates')}>Build plates{PLATES.length ? ` (${PLATES.length})` : ''}</button>
				</div>
				{#if activeTab === 'parts'}
					<span class="text-sm text-text-muted">
						{selectedParts.length}/{PARTS.length} selected ·
						<button class="text-primary hover:text-primary-hover" onclick={() => setAll(!allSelected)}>
							{allSelected ? 'deselect all' : 'select all'}
						</button>
						<button
							class="ml-3 inline-flex items-center gap-1 text-primary hover:text-primary-hover"
							onclick={downloadCsv}
							title="Exports exactly what you have set up here: {selectedParts.length ||
								PARTS.length} parts, {layers} layers, your colours, and your support choices."
						>
							<Download size={13} /> CSV
							<span class="font-normal text-text-muted"
								>· {selectedParts.length ? `${selectedParts.length} selected` : `all ${PARTS.length}`}, {layers}
								layers</span>
						</button>
					</span>
				{/if}
			</div>

			{#if activeTab === 'parts'}
				<a href="/changes" class="mb-4 flex items-center justify-between gap-4 border border-warning/60 bg-warning/[0.08] px-4 py-3 text-sm text-text transition-colors hover:bg-warning/[0.14]">
					<span><b>Changes and improvements are tracked for some parts.</b> Review what is planned before printing.</span>
					<span class="shrink-0 font-semibold text-primary">View {CHANGES.length} changes →</span>
				</a>
				{#each sectionRows as { section, parts, mult, selectedGrams } (section.id)}
				<section class="pl-sec" id="section-{section.id}">
					<h3 class="pl-sec-hd">
						{section.name}
						{#if section.scales_with_layers}
							<span class="pl-sec-mult">× {mult} layer{mult === 1 ? '' : 's'}</span>
						{/if}
						{#if section.experimental}
							<Popover width="w-80" label="Why {section.name} is experimental">
								{#snippet trigger({ toggle, open })}
									<Badge as="button" variant="warning" class="px-1.5 py-0.5 uppercase tracking-wider" onclick={toggle} aria-expanded={open}><AlertTriangle size={11} /> experimental</Badge>
								{/snippet}
								<b class="text-text">Experimental — subject to lots of change.</b>
								{#if section.experimental_note}<span class="mt-2 block border-t border-border pt-2 text-text">{section.experimental_note}</span>{/if}
							</Popover>
						{/if}
						<ChangeStatus kind="sections" id={section.id} name={section.name} />
						<span class="pl-sec-total">{grams(selectedGrams)}</span>
					</h3>
					<!-- a long part name can push the table past a phone's width; it
					     scrolls within the section rather than moving the whole page -->
					<div class="pl-scroll">
					<table class="pl-tbl">
						<thead>
							<tr>
								<th class="pl-c-check"></th>
								<th class="pl-c-thumb"></th>
								<th class="pl-c-name">Part</th>
								<th class="pl-c-each">Each</th>
								<th class="pl-c-total">Total</th>
								<th class="pl-c-dl"></th>
							</tr>
						</thead>
						<tbody>
							{#each groupBlocks(parts, section.id) as block}
								{#if block.kind === 'group'}
									{@const a = getAssembly(block.id)}
									{@const folder = getFolder(block.id)}
									{@const group = block.groupKind === 'folder' ? folder : a}
									{@const k = asmKey(section.id, `${block.groupKind}:${block.id}`)}
									{@const open = expandedAsm[k]}
									{@const allOn = asmAllOn(block.parts)}
									<!-- svelte-ignore a11y_no_noninteractive_element_interactions a11y_click_events_have_key_events -->
									<tr class="pl-row" id="assembly-{block.id}" onclick={() => toggleAsm(k)}>
										<td class="pl-c-check">
										<input
												class="setup-toggle h-4 w-4"
												type="checkbox"
												checked={allOn}
												indeterminate={!allOn && asmSomeOn(block.parts)}
												onclick={(e) => e.stopPropagation()}
												onchange={() => setAsm(block.parts, !allOn)}
											aria-label="Select every part in {group?.name}"
											disabled={!block.parts.length}
											/>
										</td>
										<td class="pl-c-thumb">
										<span class="pl-fan">
											{#if !block.parts.length}<MissingImage class="pl-thumb" />{/if}
												{#each block.parts.slice(0, 3) as bp, i (bp.id)}
													<span class="pl-thumb" style="z-index:{3 - i}"><img src={bp.render} alt={bp.name} /></span>
												{/each}
											</span>
										</td>
										<td class="pl-c-name">
											<span class="pl-name">
												{#if open}<ChevronDown size={15} class="text-text-muted" />{:else}<ChevronRight size={15} class="text-text-muted" />{/if}
												{group?.name}
												<Badge variant={block.groupKind === 'folder' ? 'neutral' : 'info'}>{block.groupKind === 'folder' ? 'Folder' : 'Assembly'}</Badge>
												{#if block.groupKind === 'assembly' && a?.status === 'stub'}<Badge variant="neutral">Coming soon</Badge>{/if}
												{#if block.groupKind === 'assembly' && a}<ChangeStatus kind="assemblies" id={a.id} name={a.name} />{/if}
											</span>
										<span class="pl-meta">{block.parts.length ? `${block.parts.length} parts · click to ${open ? 'collapse' : 'expand'}` : 'Parts and print details coming soon'}</span>
										</td>
									<td class="pl-c-each">{block.parts.length ? `${block.parts.length} parts` : '—'}</td>
									<td class="pl-c-total">{block.parts.length ? grams(asmGrams(block.parts, section.id)) : '—'}</td>
										<td class="pl-c-dl">
										{#if block.parts.length}<button
												type="button"
												class="pl-dl"
												onclick={(e) => { e.stopPropagation(); downloadZip(block.parts, `${block.id}.zip`); }}
												title="Download every STL in {group?.name}"
										><Download size={16} /></button>{/if}
										</td>
									</tr>
									{#if open}
										{#each block.parts as p (p.id)}
											{@render partRow(p, section.id, true)}
										{/each}
									{/if}
								{:else}
									{@render partRow(block.part, section.id, false)}
								{/if}
							{/each}
						</tbody>
					</table>
					</div>
				</section>
			{/each}
			{:else}
				<BuildPlates highlightPartId={null} />
			{/if}
		</div>

		<!-- RIGHT: order summary -->
		<aside class="self-start lg:sticky lg:top-6">
			<h2 class="pl-sec-hd">
				<Package size={16} class="self-center" /> What to order
			</h2>
			<div class="mb-2 flex items-center gap-2">
				<label for="surplus" class="text-sm text-text">Extra filament</label>
				<div class="flex items-center">
					<input
						id="surplus"
						class="setup-control h-8 w-14 text-center text-sm"
						type="number"
						min="0"
						max="100"
						bind:value={surplus}
						onchange={() => (surplus = Math.max(0, Math.min(100, Math.round(surplus || 0))))}
					/>
					<span class="ml-1 text-sm text-text-muted">%</span>
				</div>
			</div>
			<p class="mb-2 text-xs text-text-muted">Buffer for incidental parts &amp; failed prints.</p>
			<table class="pl-card pl-buy">
				<thead>
					<tr>
						<th>Color</th>
						<th class="pl-num">Spools</th>
						<th class="pl-num">Cost</th>
					</tr>
				</thead>
				<tbody>
					{#each buy.lines as line (line.colorId ?? '__any__')}
						<tr>
							<td>
								<span class="flex items-center gap-2">
									<span class="pl-chip pl-chip-lg" style="background:{line.color?.hex ?? 'repeating-linear-gradient(45deg,#ccc,#ccc 3px,#eee 3px,#eee 6px)'}"></span>
									<span class="leading-tight">{line.label}<br><span class="pl-buy-sub">{grams(line.grams)}</span></span>
								</span>
							</td>
							<td class="pl-num pl-num-strong">{line.spools}</td>
							<td class="pl-num">{money(line.cost)}</td>
						</tr>
					{:else}
						<tr><td colspan="3" class="pl-buy-empty">Nothing selected.</td></tr>
					{/each}
				</tbody>
				<tfoot>
					<tr>
						<td>Total · {grams(buy.totalGrams)}</td>
						<td class="pl-num">{buy.totalSpools}</td>
						<td class="pl-num">{money(buy.totalCost)}</td>
					</tr>
				</tfoot>
			</table>

			<!-- pricing note -->
			<div class="mt-2 flex gap-2 border border-border/60 bg-[var(--color-bg)] p-2.5 text-xs text-text-muted">
				<Info size={14} class="mt-0.5 shrink-0" />
				<span>
					Uses <a class="text-primary hover:text-primary-hover" href={STORE_URL} target="_blank" rel="noopener">Bambu Lab bulk pricing ↗</a>
					(PLA Matte, w/ spool): $24.99 ea, $17.99 at 4+, $16.99 at 6+. You're at
					<b>{money(buy.perSpool)}/spool</b> ({buy.totalSpools} roll{buy.totalSpools === 1 ? '' : 's'}).
				</span>
			</div>

			<div class="mt-2 flex items-center justify-between border border-border bg-[var(--color-bg)] px-3 py-2.5">
				<div class="flex items-center gap-2 text-sm text-text">
					<Clock size={15} class="text-text-muted" /> Total print time
				</div>
				<div class="text-right">
					<div class="text-base font-semibold tabular-nums text-text">{durationLong(totalPrintSeconds)}</div>
					<div class="text-xs text-text-muted">1 printer · 1 part/plate</div>
				</div>
			</div>

			<div class="mt-3 grid gap-2">
				<button
					class="setup-button-primary inline-flex h-10 items-center justify-center gap-2 px-4 text-sm font-semibold disabled:opacity-50"
					onclick={() => downloadZip(selectedParts, 'sorter-stls.zip')}
					disabled={zipping || selectedParts.length === 0}
				>
					{#if zipping}<Loader size={15} class="animate-spin" />{:else}<Download size={15} />{/if}
					Download selected ({selectedParts.length})
				</button>
				<a class="setup-button-secondary inline-flex h-10 items-center justify-center gap-2 px-4 text-sm font-semibold" href={SETTINGS.all_parts_zip} download>
					<Download size={15} /> Download all ({PARTS.length})
				</a>
			</div>
		</aside>
	</div>

	<footer class="mt-10 border-t border-border pt-4 text-xs text-text-muted">
		A machine = 1 feeder + 1 classification channel + 1 interface + 1 chute + 1 lazy Susan +
		N × (distribution frame + bins + funnels). Distribution frame, bins and funnels are per layer.
		Grams from OrcaSlicer; regenerate with <code class="font-mono">slicer/filament.py</code>.
	</footer>
</div>

<PartDetailModal bind:open={viewerOpen} part={viewerPart} bind:colorId={viewerColor} bind:version={viewerVersion} />

<Modal bind:open={platesModalOpen} title="Build plates · {partsById.get(platesModalPartId ?? '')?.name ?? ''}">
	<div class="p-4">
		<BuildPlates highlightPartId={platesModalPartId} />
	</div>
</Modal>

<style>
	/* Parts list surface. One white card per section on the warm page background,
	   square corners + a hairline border to match the rest of the app. There are
	   no rules between rows — padding does the separating — and nothing on a row
	   is heavier than 500, so size and colour carry the hierarchy. */
	.pl-sec { margin-bottom: 2.5rem; }
	.pl-sec-hd {
		display: flex; align-items: baseline; gap: 0.5rem;
		padding: 0 0.25rem 0.75rem;
		font-size: 1rem; font-weight: 500; color: var(--color-text);
	}
	.pl-sec-mult, .pl-sec-total { font-size: 0.875rem; font-weight: 400; color: var(--color-text-muted); }
	.pl-sec-total { margin-left: auto; }

	.pl-tbl {
		width: 100%;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		box-shadow: 0 1px 2px rgba(32, 28, 20, 0.03);
		border-collapse: separate; border-spacing: 0;
	}
	.pl-tbl thead th {
		font-size: 0.8125rem; font-weight: 400; text-align: right;
		color: color-mix(in oklab, var(--color-text-muted) 70%, transparent);
		padding: 1rem 1.25rem 0.625rem 0;
	}
	.pl-tbl thead th.pl-c-name { text-align: left; }
	.pl-tbl thead th:first-child { padding-left: 1.25rem; }

	.pl-row { cursor: pointer; transition: background-color 120ms; }
	.pl-row > td { padding: 0.875rem 1.25rem 0.875rem 0; vertical-align: middle; }
	.pl-row > td:first-child { padding-left: 1.25rem; }
	.pl-row:hover { background: color-mix(in oklab, var(--color-bg) 55%, transparent); }
	/* expanded assembly children sit on a tint and indent under the rollup row */
	.pl-kid { background: color-mix(in oklab, var(--color-bg) 50%, transparent); }
	.pl-kid > td:first-child { padding-left: 2.5rem; }
	.pl-kid .pl-name { color: color-mix(in oklab, var(--color-text) 88%, transparent); }

	/* The table is the page's spine and stays a table; if a long name pushes it
	   past a narrow screen it scrolls here, never dragging the page with it. */
	.pl-scroll { overflow-x: auto; }

	/* ---- phones -------------------------------------------------------------
	   The parts table is the page's spine, so it stays a table rather than
	   collapsing into cards — but 1.25rem gutters and a per-unit column don't
	   fit 375px. Tighten the padding, shrink the thumbnail, and drop "each":
	   the total is the number people act on, and each is still in the modal. */
	@media (max-width: 640px) {
		/* auto layout hands the slack to whichever column has the widest content —
		   here the thumbnail — and squeezes the names. Fixed layout honours these
		   widths instead, so the name gets everything left over. */
		.pl-tbl { table-layout: fixed; }
		.pl-tbl thead th,
		.pl-row > td { padding-right: 0.5rem; }
		.pl-tbl thead th:first-child,
		.pl-row > td:first-child { padding-left: 0.5rem; }
		.pl-kid > td:first-child { padding-left: 1.25rem; }
		.pl-c-each { display: none; }
		.pl-c-check { width: 1.75rem; }
		.pl-c-thumb { width: 2.75rem; }
		.pl-c-thumb img { width: 2.25rem; height: 2.25rem; }
		/* the rollup's fan of three thumbnails has nowhere to go in a phone's thumb
		   column — it spilled over the name. One stands in; the badge and the
		   "3 parts" line already say it's an assembly. */
		.pl-fan .pl-thumb + .pl-thumb { display: none; }
		.pl-c-name { width: auto; }
		.pl-c-total { width: 3.5rem; }
		.pl-c-dl { width: 1.5rem; }
		.pl-sec { margin-bottom: 1.75rem; }
		/* long unbroken part names would otherwise force the column wider */
		.pl-name,
		.pl-meta { overflow-wrap: anywhere; font-size: 0.875rem; }
		.pl-name { font-size: 0.9375rem; gap: 0.375rem; }
		.pl-row > td { padding-top: 0.625rem; padding-bottom: 0.625rem; }
	}

	.pl-c-check { width: 2rem; }
	.pl-c-thumb { width: 3.5rem; }
	.pl-c-name { width: 100%; text-align: left; }
	.pl-c-each, .pl-c-total { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
	.pl-c-each { font-size: 0.875rem; color: color-mix(in oklab, var(--color-text-muted) 70%, transparent); }
	.pl-c-total { font-size: 1rem; font-weight: 500; color: var(--color-text); }
	.pl-c-dl { width: 2rem; text-align: right; }

	.pl-name {
		display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
		font-size: 1rem; font-weight: 400; color: var(--color-text);
	}
	.pl-meta {
		display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
		margin-top: 0.25rem; font-size: 0.875rem;
		color: color-mix(in oklab, var(--color-text-muted) 85%, transparent);
	}
	.pl-chip { display: block; width: 0.75rem; height: 0.75rem; flex: none; border: 1px solid var(--color-border); }
	.pl-support {
		display: flex; width: fit-content; align-items: center; gap: 0.375rem;
		margin-top: 0.25rem; cursor: pointer;
		font-size: 0.8125rem; color: var(--color-text-muted);
	}

	.pl-thumb {
		display: block; position: relative; flex: none;
		width: 2.75rem; height: 2.75rem;
		background: var(--color-bg); padding: 0.125rem;
	}
	.pl-thumb img { width: 100%; height: 100%; object-fit: contain; }
	.pl-fan { display: flex; }
	.pl-fan .pl-thumb { border: 1px solid var(--color-border); background: var(--color-surface); }
	.pl-fan .pl-thumb + .pl-thumb { margin-left: -0.75rem; }

	.pl-dl { display: inline-flex; color: var(--color-primary); }
	.pl-dl:hover { color: var(--color-primary-hover); }

	/* The settings and order-summary tables share the parts list's surface and
	   type scale so the page reads as one system. */
	.pl-card {
		width: 100%;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		box-shadow: 0 1px 2px rgba(32, 28, 20, 0.03);
		border-collapse: separate; border-spacing: 0;
	}

	.pl-settings td { padding: 0.625rem 1.25rem; vertical-align: baseline; }
	.pl-settings-k {
		width: 10rem; font-size: 0.875rem; font-weight: 400;
		color: color-mix(in oklab, var(--color-text-muted) 85%, transparent);
	}
	.pl-settings-v { font-size: 0.9375rem; color: var(--color-text); }

	.pl-buy th {
		padding: 1rem 1.25rem 0.625rem; text-align: left;
		font-size: 0.8125rem; font-weight: 400;
		color: color-mix(in oklab, var(--color-text-muted) 70%, transparent);
	}
	.pl-buy td { padding: 0.75rem 1.25rem; font-size: 0.9375rem; color: var(--color-text); }
	.pl-buy .pl-num { text-align: right; font-variant-numeric: tabular-nums; }
	.pl-buy .pl-num-strong { font-weight: 500; }
	.pl-buy-sub { font-size: 0.8125rem; color: color-mix(in oklab, var(--color-text-muted) 85%, transparent); }
	.pl-buy-empty { text-align: center; color: var(--color-text-muted); padding: 1.25rem; }
	.pl-buy tfoot td {
		border-top: 1px solid var(--color-border);
		font-weight: 500;
		background: color-mix(in oklab, var(--color-bg) 55%, transparent);
	}
	.pl-chip-lg { width: 1rem; height: 1rem; }
</style>
