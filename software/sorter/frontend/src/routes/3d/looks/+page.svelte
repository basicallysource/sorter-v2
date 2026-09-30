<script lang="ts">
	// Choosing the 3D page's look side by side: each option on the same machine
	// from the same place, live (drag to turn any of them). Once one look and
	// one card style are chosen, they become the only ones and this page goes.
	import { onMount } from 'svelte';
	import AppShell from '$lib/components/AppShell.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { fetchLegoColors } from '$lib/pieces/colors';
	import {
		chuteFrame,
		layerKinds,
		placeBins,
		type BinPlace,
		type Geometry,
		type LayoutLayer
	} from '$lib/machine3d/layout';
	import { LOOKS, type LookName } from '$lib/machine3d/looks';
	import { CARD_STYLES, type CardData, type CardStyle } from '$lib/machine3d/cards';
	import { cardsFor, loadRecent, type Recent } from '$lib/machine3d/cards-data';
	import { readTheme } from '$lib/machine3d/theme';
	import type { MachineView } from '$lib/machine3d/view';

	const machine = getMachineContext();
	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());

	let tab = $state<'looks' | 'cards'>('looks');
	let error = $state<string | null>(null);
	let ready = $state(false);
	type Shared = {
		places: BinPlace[];
		kinds: string[];
		geo: Geometry;
		cards: CardData[];
		loaded: Awaited<ReturnType<(typeof import('$lib/machine3d/view'))['loadModel']>>;
		View: typeof MachineView;
	};
	let shared: Shared | null = null;

	const letter = (i: number) => String.fromCharCode(65 + i);
	const looks = LOOKS.map((l, i) => ({ id: l.name, title: `${letter(i)} · ${l.label}` }));
	const cardOptions = CARD_STYLES.map((c, i) => ({
		id: c.name,
		title: `${letter(i)} · ${c.label}`
	}));

	async function getJson<T>(path: string): Promise<T> {
		const res = await fetch(`${base}${path}`);
		if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
		return (await res.json()) as T;
	}

	/** Pictures of the recent pieces, through the backend (the picture host
	 *  sends no CORS header, and a texture needs one). */
	async function pictures(recent: Recent): Promise<Map<string, CanvasImageSource>> {
		const urls = new Set<string>();
		for (const list of recent.values())
			for (const p of list.slice(0, 4)) if (p.image) urls.add(p.image);
		const out = new Map<string, CanvasImageSource>();
		await Promise.all(
			[...urls].map(async (url) => {
				try {
					const res = await fetch(`${base}/api/piece-image?url=${encodeURIComponent(url)}`);
					if (res.ok) out.set(url, await createImageBitmap(await res.blob()));
				} catch {
					// that piece shows its colour instead
				}
			})
		);
		return out;
	}

	onMount(() => {
		void (async () => {
			try {
				const [{ MachineView, loadModel }, layout, hardware] = await Promise.all([
					import('$lib/machine3d/view'),
					getJson<{ layers: LayoutLayer[] }>('/api/bins/layout'),
					getJson<{
						chute: {
							num_sections: number;
							section_width_deg: number;
							first_section_offset_deg: number;
							max_angle_deg: number;
						};
					}>('/api/hardware-config'),
					sortingProfileStore.load(base).catch(() => null)
				]);
				const loaded = await loadModel();
				const geo: Geometry = {
					numSections: hardware.chute.num_sections,
					sectionWidthDeg: hardware.chute.section_width_deg,
					firstSectionOffsetDeg: hardware.chute.first_section_offset_deg,
					maxAngleDeg: hardware.chute.max_angle_deg
				};
				const palette = new Map(
					(await fetchLegoColors(base).catch(() => [])).map((c) => [
						String(c.id),
						c.rgb ? `#${c.rgb}` : '#888888'
					])
				);
				const recent = await loadRecent(base, palette).catch(() => null);
				const images = recent ? await pictures(recent) : new Map();
				const places = placeBins(layout.layers, geo, loaded.manifest);
				shared = {
					places,
					kinds: layerKinds(layout.layers),
					geo,
					cards: cardsFor(places, recent, images),
					loaded,
					View: MachineView
				};
				ready = true;
			} catch (e) {
				error = e instanceof Error ? e.message : String(e);
			}
		})();
	});

	/** One live view in a cell: the whole machine for a look, a close-up of a
	 *  layer's bins for a card style. */
	function cell(canvas: HTMLCanvasElement, option: { look?: LookName; card?: CardStyle }) {
		const s = shared!;
		const view = new s.View(canvas, s.loaded);
		view.setTheme(readTheme());
		view.setLayers(s.kinds);
		view.setChuteFrame(chuteFrame(s.geo, s.loaded.manifest).azimuth);
		view.setBins(s.places, s.cards);
		if (option.look) {
			view.setLook(option.look);
			view.setCardStyle('plate');
			view.setCamera({ azimuth: 35, elevation: 16, distance: 0.8 });
		}
		if (option.card) {
			view.setCardStyle(option.card);
			// The top layer's second section, face on, close.
			const bin =
				s.places.find((p) => p.layer === 0 && p.section === 1 && p.bin === 1) ?? s.places[0];
			const target = view.binFront(bin.key);
			if (target)
				view.setCamera({ azimuth: bin.faceAzimuth + 12, elevation: 14, distance: 0.26, target });
		}
		return { destroy: () => view.dispose() };
	}
</script>

<svelte:head><title>3D looks · Sorter</title></svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-[1500px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader
			title="Pick a look for the 3D page"
			description="Each one is live: drag to turn it, scroll to zoom. Say the letter of the look and of the card you want."
		>
			{#snippet actions()}
				<SegmentedControl
					bind:value={tab}
					label="What to pick"
					options={[
						{ value: 'looks', label: 'The machine' },
						{ value: 'cards', label: 'The cards on the bins' }
					]}
				/>
			{/snippet}
		</PageHeader>

		{#if error}
			<Alert tone="danger" title="The machine did not load">{error}</Alert>
		{:else if !ready}
			<div class="flex justify-center py-24"><Spinner /></div>
		{:else}
			{#key tab}
				<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 xl:grid-cols-3">
					{#each tab === 'looks' ? looks : cardOptions as option (option.id)}
						<Panel title={option.title} flush>
							<canvas
								class="block aspect-[4/3] w-full touch-none"
								aria-label={option.title}
								use:cell={tab === 'looks'
									? { look: option.id as LookName }
									: { card: option.id as CardStyle }}
							></canvas>
						</Panel>
					{/each}
				</div>
			{/key}
		{/if}
	</div>
</AppShell>
