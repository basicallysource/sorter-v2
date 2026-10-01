<script lang="ts">
	// The machine in 3D, as the software knows it: which way the chute points,
	// which door is closed, what each bin takes, and a piece on its way to a
	// bin. Click a bin for what it takes; right-click it (or use the button on
	// the side) to point the chute at it.
	//
	// State comes from the websocket's pieces as they are routed and from a
	// few slow reads, never a fast poll: the layout every 15 s, the chute and
	// the doors every 5 s while nothing is sorting, and the bins' contents
	// only when their change token moves. three.js loads only here.
	//
	// Each bin's card is a BinFrontCard in a layer behind the canvas, which
	// the view turns onto the bin's front (see view.ts).
	import { onMount, untrack } from 'svelte';
	import AppShell from '$lib/components/AppShell.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import BinFrontCard, { PIECES } from '$lib/components/machine3d/BinFrontCard.svelte';
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { categoryLabel } from '$lib/components/bins/pieces';
	import {
		binKey,
		chuteFrame,
		layerKinds,
		placeBins,
		type BinPlace,
		type Geometry,
		type LayoutLayer
	} from '$lib/machine3d/layout';
	import type { Manifest } from '$lib/machine3d/model';
	import type { DoorState, MachineView } from '$lib/machine3d/view';
	import { readTheme } from '$lib/machine3d/theme';
	import { watchContents, type Recent } from '$lib/machine3d/contents';

	const LAYOUT_EVERY_MS = 15_000;
	const LIVE_EVERY_MS = 5_000;
	const CONTENTS_EVERY_MS = 5_000;

	const machine = getMachineContext();
	// A touch screen has no right click and no wheel; the help says what it has.
	const touch = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches;
	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());
	const sorting = $derived(machine.machine?.sorterState?.state === 'running');

	let canvas: HTMLCanvasElement;
	let cardLayer: HTMLDivElement;
	let cardCamera: HTMLDivElement;
	let menu: Menu | undefined = $state();
	let view = $state.raw<MachineView | null>(null);
	let manifest = $state<Manifest | null>(null);
	let loadError = $state<string | null>(null);
	let layers = $state<LayoutLayer[]>([]);
	let geo = $state<Geometry | null>(null);
	let doors = $state<DoorState[]>([]);
	let chuteAngle = $state<number | null>(null);
	let homed = $state<boolean | null>(null);
	let selected = $state<BinPlace | null>(null);
	let hovered = $state<string | null>(null);
	let recent = $state.raw<Recent>({});
	let seeInside = $state(false);
	let aiming = $state(false);
	let aimError = $state<string | null>(null);

	const places = $derived(manifest && geo ? placeBins(layers, geo, manifest) : []);
	// The layer whose door is closed catches the next piece; the chute points
	// at a bin there.
	const catching = $derived(doors.findIndex((d) => d.calibrated && d.open < 0.5));
	const aimed = $derived.by(() => {
		if (chuteAngle === null || catching < 0 || !geo) return null;
		return (
			places.find(
				(p) =>
					p.layer === catching &&
					Math.abs(p.chuteAngle - chuteAngle!) <= geo!.sectionWidthDeg / p.binsInSection / 2
			) ?? null
		);
	});

	// ------------------------------------------------------------ reading the machine
	async function getJson<T>(path: string): Promise<T> {
		const res = await fetch(`${base}${path}`);
		if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
		return (await res.json()) as T;
	}

	type HardwareConfig = {
		storage_layers?: {
			layers: {
				index: number;
				calibrated: boolean;
				servo_open_angle: number;
				servo_closed_angle: number;
				servo_current_angle: number | null;
			}[];
		};
		chute?: {
			num_sections: number;
			section_width_deg: number;
			first_section_offset_deg: number;
			max_angle_deg: number;
		};
	};

	// A read that says what the page already has changes nothing: the bins and
	// their cards are placed again only when the layout or the chute's geometry does.
	let layoutText = '';
	let geoText = '';

	async function readLayout() {
		const data = await getJson<{ layers: LayoutLayer[]; current_angle: number | null }>(
			'/api/bins/layout'
		);
		const text = JSON.stringify(data.layers);
		if (text !== layoutText) {
			layoutText = text;
			layers = data.layers;
		}
		if (chuteAngle === null && data.current_angle !== null) chuteAngle = data.current_angle;
	}

	async function readHardware() {
		const data = await getJson<HardwareConfig>('/api/hardware-config');
		if (data.chute) {
			const next = {
				numSections: data.chute.num_sections,
				sectionWidthDeg: data.chute.section_width_deg,
				firstSectionOffsetDeg: data.chute.first_section_offset_deg,
				maxAngleDeg: data.chute.max_angle_deg
			};
			const text = JSON.stringify(next);
			if (text !== geoText) {
				geoText = text;
				geo = next;
			}
		}
		// The storage layers count from 1; the layout's layers from 0, the top.
		doors = (data.storage_layers?.layers ?? [])
			.slice()
			.sort((a, b) => a.index - b.index)
			.map((l) => {
				const span = l.servo_open_angle - l.servo_closed_angle;
				const open =
					l.servo_current_angle === null || span === 0
						? 0
						: Math.min(1, Math.max(0, (l.servo_current_angle - l.servo_closed_angle) / span));
				return { open, calibrated: l.calibrated };
			});
	}

	async function readChute() {
		const live = await getJson<{ current_angle: number | null; homed: boolean }>(
			'/api/hardware-config/chute/live'
		);
		homed = live.homed;
		if (live.current_angle !== null) chuteAngle = live.current_angle;
	}

	const contents = $derived(watchContents(base, PIECES, (next) => (recent = next)));

	// ------------------------------------------------------------ pieces on their way
	// A piece routed to a bin: the chute turns to it, its layer's door closes and
	// the others open, and the bin lights until the piece is in; then its card
	// shows it.
	const seen = new Map<string, string>();
	$effect(() => {
		const pieces = machine.machine?.recentObjects ?? [];
		if (!geo || !view) return;
		untrack(() => route(pieces));
	});

	function route(pieces: NonNullable<typeof machine.machine>['recentObjects']) {
		for (const piece of pieces) {
			const stage = piece.stage;
			if (seen.get(piece.uuid) === stage) continue;
			seen.set(piece.uuid, stage);
			const dest = piece.destination_bin as [number, number, number] | null | undefined;
			if (!dest) continue;
			const key = binKey(dest[0], dest[1], dest[2]);
			const place = places.find((p) => p.key === key);
			if (stage === 'distributing') {
				view?.lightBin(key, true);
				if (place) chuteAngle = place.chuteAngle;
				doors = doors.map((d, i) => ({ ...d, open: i === dest[0] || !d.calibrated ? 0 : 1 }));
			} else if (stage === 'distributed') {
				view?.lightBin(key, false);
				void contents.check();
			}
		}
		if (seen.size > 200) for (const uuid of [...seen.keys()].slice(0, 100)) seen.delete(uuid);
	}

	// ------------------------------------------------------------ the view
	$effect(() => {
		if (layers.length) view?.setLayers(layerKinds(layers));
	});
	$effect(() => view?.setBins(places));
	$effect(() => {
		if (view && geo && manifest) {
			const frame = chuteFrame(geo, manifest);
			view.setChuteFrame(frame.azimuth);
		}
	});
	let jumped = false;
	$effect(() => {
		if (!view || chuteAngle === null) return;
		view.setChute(chuteAngle, { jump: !jumped });
		jumped = true;
	});
	let doorsJumped = false;
	$effect(() => {
		if (!view || !doors.length) return;
		view.setDoors(doors, { jump: !doorsJumped });
		doorsJumped = true;
	});
	$effect(() => view?.setAimed(aimed?.key ?? null));
	$effect(() => view?.select(selected?.key ?? null));
	$effect(() => view?.setSeeInside(seeInside));

	// ------------------------------------------------------------ pointing
	let down: { x: number; y: number } | null = null;
	let hoverQueued = false;

	function onpointerdown(e: PointerEvent) {
		down = { x: e.clientX, y: e.clientY };
	}

	function onpointerup(e: PointerEvent) {
		if (!view || !down || e.button !== 0) return;
		const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
		down = null;
		if (moved > 4) return;
		selected = view.pick(e.clientX, e.clientY);
		aimError = null;
	}

	function onpointermove(e: PointerEvent) {
		if (!view || e.buttons !== 0 || hoverQueued) return;
		hoverQueued = true;
		requestAnimationFrame(() => {
			hoverQueued = false;
			const hit = view?.pick(e.clientX, e.clientY) ?? null;
			hovered = hit?.key ?? null;
			view?.hover(hovered);
			canvas.style.cursor = hit ? 'pointer' : '';
		});
	}

	function oncontextmenu(e: MouseEvent) {
		e.preventDefault();
		const hit = view?.pick(e.clientX, e.clientY) ?? null;
		if (!hit) return;
		selected = hit;
		aimError = null;
		menu?.openAt(e);
	}

	const aimBlocked = $derived.by(() => {
		if (!selected) return 'Pick a bin first.';
		if (sorting) return 'Pause the machine to point the chute.';
		if (homed === false) return 'Home the chute first.';
		if (!selected.reachable) return 'The chute cannot reach this bin.';
		return null;
	});

	async function aim() {
		if (!selected || aimBlocked) return;
		aiming = true;
		aimError = null;
		try {
			const res = await fetch(`${base}/api/hardware-config/chute/move-to-virtual-bin`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					num_sections: geo?.numSections ?? 6,
					bins_in_section: selected.binsInSection,
					section_index: selected.section,
					bin_index: selected.bin
				})
			});
			const body = await res.json().catch(() => null);
			if (!res.ok) throw new Error(body?.detail ?? `HTTP ${res.status}`);
			const target = body?.target_angle as number | undefined;
			const ms = body?.estimated_ms as number | undefined;
			if (typeof target === 'number') {
				view?.setChute(target, { durationMs: ms });
				chuteAngle = target;
			}
			setTimeout(() => void readChute().catch(() => {}), (ms ?? 1000) + 300);
		} catch (e) {
			aimError = e instanceof Error ? e.message : String(e);
		} finally {
			aiming = false;
		}
	}

	/** Hands a card's element to the view, which puts it on its bin. */
	function onBin(el: HTMLElement, key: string) {
		let off = view?.card(el, key);
		return {
			update(next: string) {
				off?.();
				off = view?.card(el, next);
			},
			destroy: () => off?.()
		};
	}

	const menuItems = $derived([
		{
			label: 'Point the chute here',
			icon: Crosshair,
			onselect: () => void aim(),
			disabled: !!aimBlocked
		},
		{ label: 'Open the bins page', icon: LayoutGrid, href: '/bins' }
	]);

	// ------------------------------------------------------------ start and stop
	onMount(() => {
		let stopped = false;
		const timers: ReturnType<typeof setInterval>[] = [];
		const visible = () => document.visibilityState === 'visible';
		const quiet = (p: Promise<unknown>) => p.catch((e) => console.warn('[3d]', e));

		void sortingProfileStore.load(base).catch(() => {});
		quiet(readHardware());
		quiet(readLayout());
		quiet(readChute());
		void contents.check();
		timers.push(
			setInterval(() => visible() && quiet(readLayout()), LAYOUT_EVERY_MS),
			setInterval(() => visible() && void contents.check(), CONTENTS_EVERY_MS),
			setInterval(() => {
				if (!visible() || sorting) return;
				quiet(readChute());
				quiet(readHardware());
			}, LIVE_EVERY_MS)
		);

		const themeObserver = new MutationObserver(() => view?.setTheme(readTheme()));
		themeObserver.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['class', 'style']
		});

		void (async () => {
			try {
				const { MachineView, loadModel } = await import('$lib/machine3d/view');
				const loaded = await loadModel();
				if (stopped) return;
				view = new MachineView(canvas, loaded);
				view.setCardLayer(cardLayer, cardCamera);
				view.setTheme(readTheme());
				manifest = loaded.manifest;
				if (import.meta.env.DEV) {
					(window as unknown as { machine3d: MachineView }).machine3d = view;
					if (new URLSearchParams(location.search).has('bench'))
						setTimeout(() => (bench = runBench()), 2500);
				}
			} catch (e) {
				loadError = e instanceof Error ? e.message : String(e);
			}
		})();

		const onkey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') selected = null;
		};
		window.addEventListener('keydown', onkey);

		return () => {
			stopped = true;
			timers.forEach(clearInterval);
			themeObserver.disconnect();
			window.removeEventListener('keydown', onkey);
			view?.dispose();
			view = null;
		};
	});

	// Development only: ?bench times drawing and picking on this browser and shows it.
	let bench = $state<string | null>(null);
	function runBench(): string {
		if (!view) return 'no view';
		const lines = [
			`pixel ratio ${window.devicePixelRatio}, canvas ${canvas.width}x${canvas.height}`
		];
		const plain = view.bench(40);
		lines.push(
			`frame ${plain.ms.toFixed(2)} ms, ${plain.calls} calls, ${plain.triangles} triangles`
		);
		view.setSeeInside(true);
		const inside = view.bench(40);
		view.setSeeInside(seeInside);
		lines.push(`see inside ${inside.ms.toFixed(2)} ms, ${inside.calls} calls`);
		const rect = canvas.getBoundingClientRect();
		let t = performance.now();
		for (let i = 0; i < 100; i++)
			view.pick(rect.left + Math.random() * rect.width, rect.top + Math.random() * rect.height);
		lines.push(`pick ${((performance.now() - t) / 100).toFixed(2)} ms`);
		t = performance.now();
		for (let i = 0; i < 20; i++) view.select(places[i % places.length]?.key ?? null);
		lines.push(`select ${((performance.now() - t) / 20).toFixed(2)} ms`);
		view.select(selected?.key ?? null);
		t = performance.now();
		view.setBins(places);
		lines.push(`bins and cards ${(performance.now() - t).toFixed(1)} ms`);
		return lines.join('\n');
	}

	const selectedFacts = $derived(
		selected
			? [
					{ label: 'Layer', value: selected.layer + 1 },
					{ label: 'Section', value: selected.section + 1 },
					{ label: 'Bin', value: selected.globalIndex + 1 },
					{ label: 'Chute angle', value: `${selected.chuteAngle.toFixed(1)}°` }
				]
			: []
	);
	const doorWords = (d: DoorState) =>
		!d.calibrated ? 'Not calibrated' : d.open < 0.5 ? 'Closed' : 'Open';
</script>

<svelte:head><title>3D · Sorter</title></svelte:head>

<AppShell fit>
	<div class="flex min-h-0 flex-1 flex-col gap-(--gap-panels) p-4 sm:p-6 lg:flex-row">
		<div
			class="relative h-[70dvh] min-h-0 overflow-hidden rounded-panel bg-surface lg:h-auto lg:flex-1"
		>
			<!-- Behind the canvas, which shows each card through a hole where nothing is in front of it. -->
			<div
				bind:this={cardLayer}
				class="pointer-events-none absolute inset-0 overflow-hidden"
				aria-hidden="true"
			>
				<div bind:this={cardCamera} class="absolute top-0 left-0 transform-3d">
					{#if view}
						{#each places as p (p.key)}
							<div use:onBin={p.key} class="absolute top-0 left-0">
								<BinFrontCard
									number={p.globalIndex + 1}
									name={categoryLabel(p.categoryIds)}
									pieces={recent[p.key] ?? []}
									chosen={selected?.key === p.key}
									current={aimed?.key === p.key}
									hovered={hovered === p.key}
									off={!p.enabled || !p.reachable}
								/>
							</div>
						{/each}
					{/if}
				</div>
			</div>
			<canvas
				bind:this={canvas}
				class="relative block h-full w-full touch-none select-none"
				aria-label="The machine in 3D"
				{onpointerdown}
				{onpointerup}
				{onpointermove}
				onpointerleave={() => {
					hovered = null;
					view?.hover(null);
				}}
				{oncontextmenu}
			></canvas>
			{#if !manifest && !loadError}
				<div class="absolute inset-0 flex items-center justify-center"><Spinner /></div>
			{/if}
			{#if loadError}
				<div class="absolute inset-x-4 top-4">
					<Alert tone="danger" title="The model did not load">{loadError}</Alert>
				</div>
			{/if}
			<Menu bind:this={menu} label="Bin" items={menuItems} />
			{#if import.meta.env.DEV && bench}
				<pre class="absolute bottom-3 left-3 bg-raised p-2 text-xs text-ink">{bench}</pre>
			{/if}
		</div>

		<div class="flex flex-col gap-(--gap-panels) lg:w-80 lg:shrink-0 lg:overflow-y-auto">
			<Panel title={selected ? categoryLabel(selected.categoryIds) || 'No category' : 'Bins'}>
				{#if selected}
					<div class="flex flex-col gap-3">
						<KeyValue items={selectedFacts} />
						{#if !selected.enabled}
							<p class="text-sm text-ink-muted">This bin's layer or section is turned off.</p>
						{/if}
						<Button
							variant="primary"
							icon={Crosshair}
							loading={aiming}
							disabled={!!aimBlocked}
							onclick={() => void aim()}>Point the chute here</Button
						>
						{#if aimBlocked && !aiming}
							<p class="text-sm text-ink-muted">{aimBlocked}</p>
						{/if}
						{#if aimError}
							<Alert tone="danger">{aimError}</Alert>
						{/if}
					</div>
				{:else}
					<p class="text-sm text-ink-muted">
						{#if touch}
							Tap a bin to see what it takes and to point the chute at it. Drag to turn the machine,
							pinch to zoom, and drag with two fingers to move it.
						{:else}
							Click a bin to see what it takes. Right-click one to point the chute at it. Drag to
							turn the machine, scroll to zoom, and shift-drag to move it.
						{/if}
					</p>
				{/if}
			</Panel>

			<Panel title="Machine" flush>
				<div class="divide-y divide-line">
					<SettingRow
						label="See inside"
						help="See through the frame and the bins to the chute and its doors."
					>
						<Switch bind:checked={seeInside} label="See inside" />
					</SettingRow>
					<div class="px-(--pad-panel) py-(--pad-row)">
						<KeyValue
							items={[
								{
									label: 'Chute',
									value: chuteAngle === null ? 'Unknown' : `${chuteAngle.toFixed(1)}°`
								},
								...doors.map((d, i) => ({ label: `Layer ${i + 1} door`, value: doorWords(d) }))
							]}
						/>
					</div>
				</div>
			</Panel>
		</div>
	</div>
</AppShell>
