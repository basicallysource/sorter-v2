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
		type PartVersion,
		partDownload
	} from '$lib/filament';
	import { getBambuColor } from '$lib/bambu-colors';
	import { partsCsv } from '$lib/parts-csv';
	import { download, exportSpec, filename } from '$lib/csv';
	import ColorPicker from '$lib/components/ColorPicker.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import PartDetailModal from '$lib/components/PartDetailModal.svelte';
	import AssemblyDetailModal from '$lib/components/AssemblyDetailModal.svelte';
	import IdStamp from '$lib/components/IdStamp.svelte';
	import BuildPlates from '$lib/components/BuildPlates.svelte';
	import Seo from '$lib/components/Seo.svelte';
	import { zipSync } from 'fflate';
	import { buildUses, defaultQty as sumUses, sharedParts } from '$lib/uses';
	import { printManifest, manifestFilename, type ManifestRow } from '$lib/manifest';
	import { onMount } from 'svelte';
	import { loadConfig, saveConfig, clearConfig } from '$lib/config';
	import { layerStore, addLayer as addLayerStore, removeLayerAt, setSize, setSizes } from '$lib/layers.svelte';
	import { colorStore, defaultRoleColors, resetRoleColors } from '$lib/colors.svelte';
	import SearchField from '$lib/components/search/SearchField.svelte';
	import { search, type Searchable } from '$lib/search';
	import Popover from '$lib/components/Popover.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import ChangeStatus from '$lib/components/ChangeStatus.svelte';
	import MissingImage from '$lib/components/MissingImage.svelte';
	import { Download, Package, ZoomIn, Loader, Info, Plus, X, RotateCcw, Clock, Layers3, ExternalLink, AlertTriangle, History, ChevronRight, ChevronDown, ArrowUpRight, FlaskConical } from 'lucide-svelte';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { browser } from '$app/environment';

	// ---- defaults (also used by "reset to default") -----------------------------
	const defaultFunnelSizes = (): ('third' | 'half')[] => ['third', 'third', 'half'];
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
	// What to print, as a count. Only parts whose quantity has been EDITED away
	// from what the machine needs live here; everything else follows the machine,
	// so adding a part to the catalog doesn't need a migration. 0 means "not
	// printing it", which is what the row checkbox writes.
	let qtyOverride = $state<Record<string, number>>({});
	let listView = $state<'assembly' | 'unique'>('assembly');
	let surplus = $state(15);
	let printBins = $state(false); // top-level: print bins or not (auto-selects the right bins)
	const partsById = new Map(PARTS.map((p) => [p.id, p]));
	// How many the machine needs, before any editing. Bins are governed by the
	// printBins toggle rather than a count, so they are 0 until it is on.
	function machineNeeds(id: string): number {
		const p = partsById.get(id);
		if (!p) return 0;
		if ('bins' in p.quantities && !printBins) return 0;
		return sumUses(uses.get(id));
	}
	/** How many are actually being printed. */
	function qtyOf(id: string): number {
		const over = qtyOverride[id];
		return over === undefined ? machineNeeds(id) : Math.max(0, over);
	}
	function isEdited(id: string): boolean {
		return qtyOverride[id] !== undefined && qtyOverride[id] !== machineNeeds(id);
	}
	function setQty(id: string, n: number) {
		const clean = Math.max(0, Math.round(Number(n) || 0));
		if (clean === machineNeeds(id)) delete qtyOverride[id];
		else qtyOverride[id] = clean;
	}
	function resetQty(id: string) {
		delete qtyOverride[id];
	}
	function isIncluded(id: string): boolean {
		return qtyOf(id) > 0;
	}
	/** Scale a machine-wide figure to the quantity actually being printed. */
	function qtyScale(id: string): number {
		const need = machineNeeds(id);
		return need > 0 ? qtyOf(id) / need : 0;
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
			if (c.qty) qtyOverride = { ...c.qty };
			// v1 stored a checkbox per part; a false becomes "print none of it".
			else if (c.selected)
				for (const [id, on] of Object.entries(c.selected)) if (!on) qtyOverride[id] = 0;
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
		const aid = sp.get('assembly');
		if (aid && getAssembly(aid)) openAssembly(aid);
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
		if (asmOpen && asmId) params.set('assembly', asmId);
		else params.delete('assembly');
		const qs = params.toString();
		const target = qs ? `${location.pathname}?${qs}` : location.pathname;
		if (target !== location.pathname + location.search) replaceState(target, {});
	});
	$effect(() => {
		const snapshot = { printBins, surplus, qty: qtyOverride, inclSupport };
		if (configLoaded) saveConfig($state.snapshot(snapshot));
	});
	function resetToDefaults() {
		setSizes(defaultFunnelSizes());
		resetRoleColors();
		qtyOverride = {};
		inclSupport = defaultInclSupport();
		surplus = 15;
		printBins = false;
		clearConfig();
	}
	let zipping = $state(false);
	// One choice over every download this page hands out: the row arrows, the
	// selected-parts zip and the all-parts bundle all carry each part's version
	// id recessed into its default face while this is on. Same meaning as the
	// checkbox on a part's own page. (catalog/engrave.py)
	let engraveIds = $state(true);
	let activeTab = $state<'parts' | 'plates'>('parts');
	let platesModalOpen = $state(false);
	let platesModalPartId = $state<string | null>(null);
	function openPlatesModal(id: string) {
		platesModalPartId = id;
		platesModalOpen = true;
	}
	// The assembly modal: the rollup rows and the assembly tab open the same view
	// of one box. Held here (not inside the modal) so it can be deep-linked, the
	// same way the part viewer is.
	let asmOpen = $state(false);
	let asmId = $state<string | null>(null);
	function openAssembly(id: string) {
		asmId = id;
		asmOpen = true;
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

	// Every part's places-it-is-used, reconciled against the section quantities
	// (see $lib/uses). The assembly tree supplies the grouping; anything it can't
	// account for lands in an explicit bucket so the counts always add up.
	const uses = $derived(buildUses(layers, variantCount));
	const shared = $derived(sharedParts(uses));
	function usedIn(id: string): string[] {
		return (uses.get(id) ?? []).map((u) => u.assemblyName);
	}
	/** The assembly a part is filed under in the by-assembly view: the first one
	 *  the machine tree walks into. A part used in several places is listed once,
	 *  under the first, and carries a marker naming the others. */
	function primaryAssembly(id: string): string | null {
		return (uses.get(id) ?? []).find((u) => u.assemblyId)?.assemblyId ?? null;
	}

	// ---- filtering the list ------------------------------------------------
	// Narrows what is on screen and nothing else: the totals below still describe
	// the whole build, because a filter answers "where is it" and must not quietly
	// restate what you are about to print. It ranks through the same matcher as
	// the ⌘K palette, so a part found one way is found the other way.
	let partFilter = $state('');
	const filtering = $derived(partFilter.trim().length > 0);
	const partSearchable = (p: Part): Searchable => ({
		name: p.name,
		uid: p.uid,
		id: p.id,
		keywords: [...(p.aliases ?? []), ...usedIn(p.id), getFolder(p.folder ?? null)?.name ?? ''].filter(Boolean),
		text: p.description
	});
	function filterParts(list: Part[]): Part[] {
		if (!filtering) return list;
		return search(partFilter, list, partSearchable).map((r) => r.item);
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
		buyList(layers, roleColors, qtyOf, supportOn, variantCount, surplus)
	);

	// theoretical total print time: every included part printed alone, sequentially,
	// on one printer (one part per plate — no batching)
	const totalPrintSeconds = $derived(
		PARTS.reduce((sum, p) => sum + p.print_seconds * qtyOf(p.id), 0)
	);

	const sectionRows = $derived(
		SECTIONS.map((s) => {
			const all = PARTS.filter((p) => sectionQty(p, s.id) > 0);
			const mult = categoryMultiplier(s.id, layers);
			// over the whole section, not the filtered view — the header states what
			// the section weighs, which doesn't change because you typed something
			const selectedGrams = all.reduce(
				(sum, p) =>
					sum +
					effectiveGrams(p, supportOn(p.id)) *
						displayCount(p, s.id, layers, variantCount) *
						qtyScale(p.id),
				0
			);
			return { section: s, parts: filterParts(all), mult, selectedGrams };
		}).filter((r) => r.parts.length > 0)
	);
	/** Rows on screen in the by-assembly view, against rows there would be with no
	 *  filter. A part counted in two sections is listed in both, so both halves of
	 *  the ratio count (part, section) pairs and the two agree. */
	const sectionShown = $derived(sectionRows.reduce((n, r) => n + r.parts.length, 0));
	const sectionTotal = $derived(
		SECTIONS.reduce((n, s) => n + PARTS.filter((p) => sectionQty(p, s.id) > 0).length, 0)
	);

	const selectedParts = $derived(PARTS.filter((p) => isIncluded(p.id)));

	// The flat view: every part in the build exactly once, alphabetical, with the
	// count it is being printed at. Parts with no section (a candidate's parts)
	// are not in the build and are not listed.
	const uniqueRows = $derived(
		PARTS.filter((p) => Object.keys(p.quantities).length > 0)
			.map((p) => ({ p, qty: qtyOf(p.id), need: machineNeeds(p.id) }))
			.sort((a, b) => a.p.name.localeCompare(b.p.name))
	);
	// While filtering the rows come back in relevance order — alphabetical is only
	// useful when you are scanning the whole list.
	const uniqueShown = $derived.by(() => {
		if (!filtering) return uniqueRows;
		const keep = new Map(uniqueRows.map((r) => [r.p.id, r]));
		return filterParts(uniqueRows.map((r) => r.p)).map((p) => keep.get(p.id)!);
	});
	const uniqueGrams = $derived(
		uniqueRows.reduce((sum, r) => sum + effectiveGrams(r.p, supportOn(r.p.id)) * r.qty, 0)
	);

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
	const allSelected = $derived(PARTS.every((p) => machineNeeds(p.id) === 0 || qtyOf(p.id) > 0));

	const prettyPattern = SETTINGS.infill_pattern.replace('adaptivecubic', 'adaptive cubic');
	// both boxes at the top of the page start closed, so their one-line summary is
	// what most visits read; the parts list is the page.
	let showSettings = $state(false);
	let showBuild = $state(false);
	const settingsSummary = `Bambu Lab A1 · 0.20 mm layers · ${SETTINGS.infill_density} ${prettyPattern} · ${SETTINGS.filament}`;
	const buildSummary = $derived(
		[
			`${layers} layer${layers === 1 ? '' : 's'}`,
			`${funnelSizes.map((sz) => (sz === 'half' ? '12' : '18')).join('/')} bins`,
			printBins ? 'bins included' : 'bins not printed',
			COLOR_ROLES.map((r) => getBambuColor(roleColors[r.id])?.name ?? roleColors[r.id]).join(', ')
		].join('  ·  ')
	);
	const settingsRows: [string, string][] = [
		['Printer', 'Bambu Lab A1 · 0.4 mm'],
		['Layer height', '0.20 mm'],
		['Infill', `${SETTINGS.infill_density} ${prettyPattern}`],
		['Supports', `Off (per part; stator: normal ≤${SETTINGS.support_threshold_deg}°)`],
		['Skirt', 'None'],
		['Filament', `${SETTINGS.filament} · ${SETTINGS.density_g_cm3} g/cm³`]
	];

	function setAll(v: boolean) {
		for (const p of PARTS) {
			if ('bins' in p.quantities) continue; // the printBins toggle owns these
			if (v) resetQty(p.id);
			else setQty(p.id, 0);
		}
	}

	type Block =
		| { kind: 'part'; part: Part }
		| { kind: 'group'; groupKind: 'assembly' | 'folder'; id: string; parts: Part[] };
	function groupBlocks(parts: Part[], sectionId: string): Block[] {
		const blocks: Block[] = [];
		const represented = new Set<string>();
		// The assembly comes from the machine tree (which assembly LISTS this part),
		// never from a field on the part: one part is used in several assemblies and
		// a single field cannot say so. Members of a group need not be adjacent in
		// the catalog, so a group is placed where its first member appears and the
		// rest join it there.
		const byGroup = new Map<string, Extract<Block, { kind: 'group' }>>();
		for (const p of parts) {
			const asmId = primaryAssembly(p.id);
			const groupKind = p.folder ? 'folder' : asmId ? 'assembly' : null;
			const groupId = p.folder ?? asmId;
			if (!groupKind || !groupId) {
				blocks.push({ kind: 'part', part: p });
				continue;
			}
			if (groupKind === 'assembly') represented.add(groupId);
			const key = `${groupKind}:${groupId}`;
			let g = byGroup.get(key);
			if (!g) {
				g = { kind: 'group', groupKind, id: groupId, parts: [] };
				byGroup.set(key, g);
				blocks.push(g);
			}
			g.parts.push(p);
		}
		// Stubs are placeholders for assemblies with nothing in them yet. They match
		// nothing, so while a filter is on they are noise around the thing you asked for.
		if (!filtering)
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
					? effectiveGrams(p, supportOn(p.id)) * displayCount(p, sectionId, layers, variantCount) * qtyScale(p.id)
					: 0),
			0
		);
	}
	const asmAllOn = (parts: Part[]) => parts.every((p) => isIncluded(p.id));
	const asmSomeOn = (parts: Part[]) => parts.some((p) => isIncluded(p.id));
	// bins are governed by the Print bins toggle, so the rollup checkbox skips them
	function setAsm(parts: Part[], v: boolean) {
		for (const p of parts) {
			if ('bins' in p.quantities) continue;
			if (v) resetQty(p.id);
			else setQty(p.id, 0);
		}
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
	/** What to print, as rows: the same data the manifest and the zip both need. */
	function manifestRows(parts: Part[]): ManifestRow[] {
		return parts.map((p) => {
			const url = partDownload(p, engraveIds);
			const colorId = primaryColorId(p, roleColors);
			return {
				part: p,
				qty: qtyOf(p.id),
				defaultQty: machineNeeds(p.id),
				gramsEach: effectiveGrams(p, supportOn(p.id)),
				colorName: colorId ? (getBambuColor(colorId)?.name ?? colorId) : 'Any color',
				file: url.slice(url.lastIndexOf('/') + 1),
				usedIn: usedIn(p.id)
			};
		});
	}
	function downloadManifest() {
		const spec = exportSpec(layers);
		const body = printManifest(manifestRows(selectedParts), spec, funnelSizes);
		const url = URL.createObjectURL(new Blob([body], { type: 'text/plain;charset=utf-8' }));
		const a = document.createElement('a');
		a.href = url;
		a.download = manifestFilename(spec);
		a.click();
		URL.revokeObjectURL(url);
	}

	async function downloadZip(parts: Part[], name: string) {
		if (!parts.length) return;
		zipping = true;
		try {
			const files: Record<string, Uint8Array> = {};
			for (const p of parts) {
				const url = partDownload(p, engraveIds);
				const res = await fetch(url);
				// the bucket's own filename, <part>-<uid>[-stamped-<face>]-<hash8>.stl,
				// so the id survives into whatever the slicer names the project
				files[url.slice(url.lastIndexOf('/') + 1)] = new Uint8Array(await res.arrayBuffer());
			}
			// A zip of forty hash-named STLs says nothing about how many of each to
			// run. The manifest rides along and answers exactly that.
			files['print-manifest.txt'] = new TextEncoder().encode(
				printManifest(manifestRows(parts), exportSpec(layers), funnelSizes)
			);
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

	<!-- print settings and build options: two boxes that say what they hold -->
	<div class="mb-6 flex flex-col gap-3">
	<Disclosure title="Print settings" summary={settingsSummary} bind:open={showSettings} flush>
		<table class="pl-settings w-full max-w-xl">
			<tbody>
				{#each settingsRows as [k, v] (k)}
					<tr>
						<td class="pl-settings-k">{k}</td>
						<td class="pl-settings-v">{v}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</Disclosure>

	<!-- BUILD OPTIONS = colors + layer configuration -->
	<Disclosure title="Build options" summary={buildSummary} bind:open={showBuild} flush>
		{#snippet actions()}
			<button
				class="inline-flex items-center gap-1.5 text-sm text-text-muted hover:text-text"
				onclick={resetToDefaults}
				title="Reset all build options to defaults"
			>
				<RotateCcw size={14} /> Reset to default
			</button>
		{/snippet}

		<!-- colors -->
		<div class="p-4">
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
		<div class="border-t border-border p-4">
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
	</Disclosure>
	</div>

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
					<input class="setup-toggle h-4 w-4" type="checkbox" checked={qtyOf(p.id) > 0} onchange={(e) => (e.currentTarget.checked ? resetQty(p.id) : setQty(p.id, 0))} aria-label="Print {p.name}" />
				{/if}
			</td>
			<td class="pl-c-thumb">
				<span class="pl-thumbwrap">
					<!-- empty twist slot: keeps a part's thumbnail on the same line as
					     the fans on the assembly rows above it -->
					<span class="pl-twist"></span>
					<button
						type="button"
						class="pl-thumb group relative"
						onclick={() => openViewer(p)}
						title="View {p.name} in 3D"
					>
						<img src={p.render} alt={p.name} />
						<span class="absolute inset-0 flex items-center justify-center bg-black/40 text-white opacity-0 transition-opacity group-hover:opacity-100 group-hover/row:opacity-100"><ZoomIn size={16} /></span>
					</button>
				</span>
			</td>
			<td class="pl-c-name">
				<span class="pl-name">
					{p.name}
					{#if shared.has(p.id)}<span class="cursor-help border border-border px-1 text-xs text-text-muted" title="Also used in {usedIn(p.id).slice(1).join(', ')}">used in {usedIn(p.id).length} places</span>{/if}
					{#if isEdited(p.id)}<span class="border border-primary/60 px-1 text-xs text-primary" title="Printing {qtyOf(p.id)}, the machine needs {machineNeeds(p.id)}">qty {qtyOf(p.id)}</span>{/if}
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
				<a class="pl-dl" href={partDownload(p, engraveIds)} download title="Download {p.name}.stl{engraveIds && p.stamped?.[0] ? ` (id ${p.uid.toUpperCase()} on the ${p.stamped[0].face})` : ''}"><Download size={16} /></a>
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
						<button
							class="ml-3 inline-flex items-center gap-1 text-primary hover:text-primary-hover"
							onclick={downloadManifest}
							title="What to print and how many of each, as plain text. The same file rides inside the STL zip."
						>
							<Download size={13} /> Manifest
						</button>
					</span>
				{/if}
			</div>

			{#if activeTab === 'parts'}
				<a href="/changes" class="mb-4 flex items-center justify-between gap-4 border border-warning/60 bg-warning/[0.08] px-4 py-3 text-sm text-text transition-colors hover:bg-warning/[0.14]">
					<span><b>Changes and improvements are tracked for some parts.</b> Review what is planned before printing.</span>
					<span class="shrink-0 font-semibold text-primary">View {CHANGES.length} potential changes →</span>
				</a>
				<div class="mb-4 flex flex-wrap items-center gap-2">
					<div class="inline-flex border border-border">
						<button
							class="px-3 py-1.5 text-sm font-semibold {listView === 'assembly' ? 'bg-[var(--color-bg)] text-text' : 'text-text-muted hover:text-text'}"
							onclick={() => (listView = 'assembly')}
							aria-pressed={listView === 'assembly'}
							title="Grouped by what bolts to what. A part used in several places is listed under the first and marked.">By assembly</button>
						<button
							class="border-l border-border px-3 py-1.5 text-sm font-semibold {listView === 'unique' ? 'bg-[var(--color-bg)] text-text' : 'text-text-muted hover:text-text'}"
							onclick={() => (listView = 'unique')}
							aria-pressed={listView === 'unique'}
							title="Every part once, with the number you are printing. This is the list you print from.">By unique part</button>
					</div>
					<SearchField
						bind:value={partFilter}
						label="Filter the parts list"
						placeholder="Filter parts by name, id or where they go"
						noun="part"
						found={listView === 'unique' ? uniqueShown.length : sectionShown}
						total={listView === 'unique' ? uniqueRows.length : sectionTotal}
						class="min-w-0 flex-1"
					/>
				</div>
				{#if listView === 'unique'}
					<div class="pl-scroll mb-6">
						<table class="pl-tbl">
							<thead>
								<tr>
									<th class="pl-c-thumb"></th>
									<th class="pl-c-name">Part</th>
									<th class="pl-c-each">Each</th>
									<th class="pl-c-total">Qty</th>
									<th class="pl-c-total">Total</th>
									<th class="pl-c-dl"></th>
								</tr>
							</thead>
							<tbody>
								{#each uniqueShown as { p, qty, need } (p.id)}
									{@const each = effectiveGrams(p, supportOn(p.id))}
									<tr class="pl-row group/row" class:opacity-50={qty === 0}>
										<td class="pl-c-thumb">
											<button type="button" class="pl-thumb group relative" onclick={() => openViewer(p)} title="View {p.name} in 3D">
												<img src={p.render} alt={p.name} />
												<span class="absolute inset-0 flex items-center justify-center bg-black/40 text-white opacity-0 transition-opacity group-hover:opacity-100"><ZoomIn size={16} /></span>
											</button>
										</td>
										<td class="pl-c-name">
											<span class="pl-name">
												{p.name}
												{#if shared.has(p.id)}<span class="cursor-help border border-border px-1 text-xs text-text-muted" title="Used in {usedIn(p.id).join(', ')}">used in {usedIn(p.id).length} places</span>{/if}
												{#if p.optional}<Badge variant="warning">Optional</Badge>{/if}
												<ChangeStatus kind="parts" id={p.id} name={p.name} />
											</span>
											<span class="pl-meta">{usedIn(p.id).join(' · ') || 'not placed yet'}</span>
										</td>
										<td class="pl-c-each">{grams(each)}</td>
										<td class="pl-c-total">
											<span class="inline-flex items-center gap-1">
												<input
													class="setup-control h-7 w-16 text-center text-sm"
													type="number"
													min="0"
													value={qty}
													aria-label="How many {p.name} to print"
													onchange={(e) => setQty(p.id, e.currentTarget.valueAsNumber)}
												/>
												{#if isEdited(p.id)}
													<button
														type="button"
														class="text-text-muted hover:text-primary"
														onclick={() => resetQty(p.id)}
														title="Back to {need}, what the machine needs"
														aria-label="Reset {p.name} to {need}"><RotateCcw size={13} /></button>
												{/if}
											</span>
										</td>
										<td class="pl-c-total">{grams(each * qty)}</td>
										<td class="pl-c-dl">
											<a href={partDownload(p, engraveIds)} download class="text-text-muted hover:text-primary" title="Download {p.name}"><Download size={16} /></a>
										</td>
									</tr>
								{/each}
							</tbody>
							<tfoot>
								<tr>
									<td></td>
									<td class="pl-c-name"><span class="pl-name">{uniqueRows.filter((r) => r.qty > 0).length} parts · {uniqueRows.reduce((n, r) => n + r.qty, 0)} pieces{#if filtering}<span class="font-normal text-text-muted"> · the whole build, not the filtered rows</span>{/if}</span></td>
									<td></td>
									<td></td>
									<td class="pl-c-total">{grams(uniqueGrams)}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>
				{:else}
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
									{@const open = expandedAsm[k] || filtering}
									{@const allOn = asmAllOn(block.parts)}
									<!-- svelte-ignore a11y_no_noninteractive_element_interactions a11y_click_events_have_key_events -->
									<tr
										class="pl-row"
										id="assembly-{block.id}"
										onclick={() => (a ? openAssembly(a.id) : toggleAsm(k))}
										title={a ? `View ${a.name}` : undefined}
									>
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
											<span class="pl-thumbwrap">
												<!-- The only control that expands the members in place. Everything
												     else on the row opens the assembly itself. -->
												{#if block.parts.length}
													<button
														type="button"
														class="pl-twist"
														onclick={(e) => { e.stopPropagation(); toggleAsm(k); }}
														aria-expanded={!!open}
														aria-label="{open ? 'Hide' : 'Show'} the parts inside {group?.name}"
														title="{open ? 'Hide' : 'Show'} the {block.parts.length} parts inside"
													>
														{#if open}<ChevronDown size={15} />{:else}<ChevronRight size={15} />{/if}
													</button>
												{:else}<span class="pl-twist"></span>{/if}
												<span class="pl-fan">
													{#if !block.parts.length}<MissingImage class="pl-thumb" />{/if}
													{#each block.parts.slice(0, 3) as bp, i (bp.id)}
														<span class="pl-thumb" style="z-index:{3 - i}"><img src={bp.render} alt={bp.name} /></span>
													{/each}
												</span>
											</span>
										</td>
										<td class="pl-c-name">
											<span class="pl-nameblock" class:pl-open={!!a}>
												<span class="pl-name">
													{group?.name}
													<Badge variant={block.groupKind === 'folder' ? 'neutral' : 'info'}>{block.groupKind === 'folder' ? 'Folder' : 'Assembly'}</Badge>
													{#if block.groupKind === 'assembly' && a?.status === 'stub'}<Badge variant="neutral">Coming soon</Badge>{/if}
													{#if a?.candidates?.some((c) => !c.superseded_by && !c.rejected_at)}<Badge variant="info"><FlaskConical size={11} /> Candidate</Badge>{/if}
													{#if block.groupKind === 'assembly' && a}<ChangeStatus kind="assemblies" id={a.id} name={a.name} />{/if}
												</span>
												<span class="pl-meta">
													{block.parts.length ? `${block.parts.length} printed parts` : 'Parts and print details coming soon'}
													{#if a}<span class="pl-hint">View assembly <ArrowUpRight size={12} /></span>{:else if block.parts.length && !filtering}· click to {open ? 'collapse' : 'expand'}{/if}
												</span>
											</span>
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
				{/if}
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
				<div class="flex items-center justify-end gap-1.5"><IdStamp where="global" bind:on={engraveIds} /></div>
				<button
					class="setup-button-primary inline-flex h-10 items-center justify-center gap-2 px-4 text-sm font-semibold disabled:opacity-50"
					onclick={() => downloadZip(selectedParts, 'sorter-stls.zip')}
					disabled={zipping || selectedParts.length === 0}
				>
					{#if zipping}<Loader size={15} class="animate-spin" />{:else}<Download size={15} />{/if}
					Download selected ({selectedParts.length})
				</button>
				<a class="setup-button-secondary inline-flex h-10 items-center justify-center gap-2 px-4 text-sm font-semibold" href={engraveIds ? SETTINGS.all_parts_zip : SETTINGS.all_parts_plain_zip} download>
					<Download size={15} /> Download all ({PARTS.length})
				</a>
			</div>
		</aside>
	</div>

	<footer class="mt-10 border-t border-border pt-4 text-xs text-text-muted">
		A machine = 1 feeder + 1 classification channel + 1 interface + 1 chute + 1 lazy Susan +
		N × (distribution frame + bins + funnels). Distribution frame, bins and funnels are per layer.
		Grams from OrcaSlicer; regenerate with <code class="font-mono">catalog/generate.py</code>.
	</footer>
</div>

<AssemblyDetailModal bind:open={asmOpen} id={asmId} {layers} onPart={(p) => openViewer(p)} />
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
		/* Prefixed with .pl-tbl on purpose: the desktop column widths below are
		   written after this block, so a bare .pl-c-* here loses to them and the
		   phone layout silently keeps desktop widths. Costs one class of
		   specificity; buys the tightening this block exists for. */
		.pl-tbl .pl-c-check { width: 1.75rem; }
		/* twist slot + thumbnail have to fit inside the fixed column, borders and
		   all, or the name cell begins underneath the image */
		.pl-tbl .pl-c-thumb { width: 4.75rem; }
		.pl-c-thumb .pl-thumb { width: 2.25rem; height: 2.25rem; }
		/* the rollup's fan of three thumbnails has nowhere to go in a phone's thumb
		   column — it spilled over the name. One stands in; the badge and the
		   "3 parts" line already say it's an assembly. */
		.pl-fan .pl-thumb + .pl-thumb { display: none; }
		.pl-c-name { width: auto; }
		.pl-tbl .pl-c-total { width: 3.5rem; }
		.pl-tbl .pl-c-dl { width: 1.5rem; }
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

	/* An assembly row is a door, not a disclosure widget. The name and its count
	   are drawn as one object you open; the chevron beside the thumbnails is the
	   only thing that expands the members in place. Part rows keep an empty twist
	   slot so their single thumbnail lines up with the fans above it. */
	.pl-thumbwrap { display: flex; align-items: center; gap: 0.25rem; }
	.pl-twist {
		display: inline-flex; align-items: center; justify-content: center;
		width: 1.125rem; height: 1.5rem; flex: none;
		color: var(--color-text-muted);
	}
	button.pl-twist { cursor: pointer; transition: color 120ms; }
	button.pl-twist:hover, button.pl-twist:focus-visible { outline: none; color: var(--color-primary); }

	.pl-nameblock { display: block; }
	.pl-open {
		/* No negative margin to pull the text back into line with the part rows
		   below: at 375px the name cell is narrow enough that the box would slide
		   under the thumbnail. The half-rem inset reads as hierarchy anyway. */
		display: inline-block; padding: 0.3125rem 0.5rem;
		border: 1px solid var(--color-border); background: var(--color-bg);
		transition: border-color 120ms ease, background-color 120ms ease;
	}
	.pl-row:hover .pl-open, .pl-row:focus-within .pl-open {
		border-color: var(--color-primary);
		background: color-mix(in oklab, var(--color-primary) 6%, var(--color-bg));
	}
	.pl-hint { display: inline-flex; align-items: center; gap: 0.125rem; color: var(--color-primary); }

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
