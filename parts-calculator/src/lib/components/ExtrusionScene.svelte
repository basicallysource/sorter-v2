<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
	import { lengthGroups, STOCK_MM, type LengthGroup } from '$lib/framing';
	import { extrusionGeometry, aluminiumMaterial } from '$lib/extrusion';
	import { layerStore } from '$lib/layers.svelte';

	// optional panel rendered beside the 3D view (splits the view area 50/50)
	let { aside }: { aside?: Snippet } = $props();

	const n = $derived(layerStore.sizes.length);
	const groups = $derived(lengthGroups(n));

	// how many rods we actually draw in a bundle (quantity still shown as ×N in the
	// legend). Capping keeps a 36-piece bundle from dwarfing the bars.
	const SHOWN_CAP = 9;
	const SPACING = 21; // mm between rod centres in a bundle
	const ROW_PITCH = 95; // mm vertical gap between length rows

	let host: HTMLDivElement;
	// set inside onMount; the effect below drives (re)builds when groups change
	let rebuild = $state<((gs: LengthGroup[]) => void) | null>(null);

	$effect(() => {
		const gs = groups;
		rebuild?.(gs);
	});

	// hex-disc packing offsets for a bundle cross-section (returns [y, z] pairs)
	function bundleOffsets(count: number): [number, number][] {
		const pts: [number, number, number][] = [];
		const R = 6;
		for (let q = -R; q <= R; q++)
			for (let r = -R; r <= R; r++) {
				const x = SPACING * (q + r / 2);
				const y = SPACING * ((Math.sqrt(3) / 2) * r);
				pts.push([x, y, Math.hypot(x, y)]);
			}
		pts.sort((a, b) => a[2] - b[2]);
		return pts.slice(0, count).map((p) => [p[0], p[1]] as [number, number]);
	}

	onMount(() => {
		const el = host;
		const scene = new THREE.Scene();
		scene.background = null;

		const camera = new THREE.PerspectiveCamera(38, 1, 1, 20000);
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		// buffer is sized via setSize(…, false); pin the element to its box via CSS
		renderer.domElement.style.display = 'block';
		renderer.domElement.style.width = '100%';
		renderer.domElement.style.height = '100%';
		el.appendChild(renderer.domElement);

		// soft studio reflections so the metal reads as metal
		const pmrem = new THREE.PMREMGenerator(renderer);
		scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

		scene.add(new THREE.HemisphereLight(0xffffff, 0x555555, 0.6));
		const key = new THREE.DirectionalLight(0xffffff, 1.6);
		key.position.set(0.6, 1, 0.8);
		scene.add(key);
		const fill = new THREE.DirectionalLight(0xffffff, 0.5);
		fill.position.set(-0.5, 0.3, -0.4);
		scene.add(fill);

		const material = aluminiumMaterial();
		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;

		let bars: THREE.Group | null = null;
		let geometries: THREE.BufferGeometry[] = [];

		// (re)build the whole family for a given set of length groups
		function build(gs: LengthGroup[]) {
			if (bars) {
				scene.remove(bars);
				geometries.forEach((g) => g.dispose());
				geometries = [];
			}
			const group = new THREE.Group();
			const maxLen = Math.max(...gs.map((g) => g.len), 1);
			const topY = ((gs.length - 1) * ROW_PITCH) / 2;
			gs.forEach((g, i) => {
				const geo = extrusionGeometry(g.len);
				geometries.push(geo);
				const rowY = topY - i * ROW_PITCH;
				for (const [oy, oz] of bundleOffsets(Math.min(g.qty, SHOWN_CAP))) {
					const mesh = new THREE.Mesh(geo, material);
					mesh.rotation.y = Math.PI / 2; // extrude axis (+Z) → world +X
					mesh.position.set(-maxLen / 2, rowY + oy, oz);
					group.add(mesh);
				}
			});
			bars = group;
			scene.add(bars);
			fitCamera();
		}

		const dir = new THREE.Vector3(0.2, 0.32, 1).normalize();
		function fitCamera() {
			if (!bars) return;
			const box = new THREE.Box3().setFromObject(bars);
			const center = box.getCenter(new THREE.Vector3());
			const size = box.getSize(new THREE.Vector3());
			const radius = 0.5 * Math.hypot(size.x, size.y, size.z);
			const vFov = (camera.fov * Math.PI) / 180;
			const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
			const dist = (radius / Math.sin(Math.min(vFov, hFov) / 2)) * 1.2;
			camera.position.copy(center).addScaledVector(dir, dist);
			camera.near = Math.max(1, dist - radius * 2);
			camera.far = dist + radius * 4;
			camera.updateProjectionMatrix();
			controls.target.copy(center);
			controls.update();
		}

		function resize() {
			const w = el.clientWidth || 1;
			const h = el.clientHeight || 1;
			renderer.setSize(w, h, false);
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		}
		resize();
		const ro = new ResizeObserver(resize);
		ro.observe(el);

		// hand the build fn to the reactive effect (fires now + on layer changes)
		rebuild = build;

		let raf = 0;
		function loop() {
			controls.update();
			renderer.render(scene, camera);
			raf = requestAnimationFrame(loop);
		}
		loop();

		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			controls.dispose();
			material.dispose();
			geometries.forEach((g) => g.dispose());
			pmrem.dispose();
			renderer.dispose();
			renderer.domElement.remove();
		};
	});
</script>

<div class="setup-card-shell border">
	<div class="border-b border-border px-4 py-2.5">
		<h3 class="text-base font-semibold text-text">Piece family</h3>
		<p class="text-sm text-text-muted">
			2020 extrusion · each length drawn to scale, bundled by quantity
		</p>
	</div>

	<div class="flex">
		<div class="relative h-[42vh] {aside ? 'w-1/2' : 'w-full'} bg-[var(--color-bg)]">
			<div bind:this={host} class="h-full w-full"></div>
			<div class="pointer-events-none absolute bottom-2 left-3 text-xs text-text-muted">
				drag to rotate · scroll to zoom
			</div>
		</div>
		{#if aside}
			<div class="w-1/2 border-l border-border">{@render aside()}</div>
		{/if}
	</div>

	<!-- legend: same top→bottom order as the rows -->
	<table class="w-full text-sm">
		<tbody>
			{#each groups as g (g.len)}
				<tr class="border-t border-border">
					<td class="w-12 py-1.5 pl-4">
						<span class="font-mono text-xs font-semibold text-text">{g.label}</span>
					</td>
					<td class="py-1.5 pr-2 text-text">{g.names.join(' / ')}</td>
					<td class="whitespace-nowrap py-1.5 pr-2 text-right text-xs text-text-muted">
						{g.category === 'per-layer' ? 'per layer' : g.category === 'per-machine' ? 'per machine' : ''}
					</td>
					<td class="whitespace-nowrap py-1.5 pr-2 text-right font-mono tabular-nums text-text">
						{g.len} mm
					</td>
					<td class="whitespace-nowrap py-1.5 pr-4 text-right text-xs text-text-muted">× {g.qty}</td>
				</tr>
			{/each}
		</tbody>
		<tfoot>
			<tr class="border-t border-border bg-[var(--color-bg)] text-sm text-text-muted">
				<td colspan="5" class="px-4 py-2">
					Stock: {STOCK_MM} mm bars · profile 2020 T-slot · {n} layer{n === 1 ? '' : 's'}. Renders are
					generated live from the true cross-section — no baked images.
				</td>
			</tr>
		</tfoot>
	</table>
</div>
