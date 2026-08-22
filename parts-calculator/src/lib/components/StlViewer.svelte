<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

	// The 3D preview. Lit the way CAD lights a part: flat ambient plus one
	// headlight riding on the camera, no tone mapping, no rim or fill -- a face
	// is brighter the more it faces you, and that is all the shading there is.
	//
	// `url` swaps geometry in place: the camera stays where it is, so flipping
	// through stamped faces reads as the mark moving, not a reload. `mark` is
	// the uid stamp's location on that geometry (catalog/engrave.py writes
	// center / normal / size in the STL's own coordinates); its pocket is
	// painted in the accent colour so it can be found at any zoom, and
	// `viewMark()` flies the camera to look straight at it. `resetView()` goes
	// back to the whole part.
	let {
		url,
		color = '#0055bf',
		mark = null,
		heightClass = 'h-[48vh]'
	}: {
		url: string;
		color?: string;
		mark?: {
			center: number[];
			normal: number[];
			size: number[];
			surface?: { axis: number[]; point: number[]; r0: number; slope: number; sign: number };
		} | null;
		heightClass?: string;
	} = $props();

	const ACCENT = '#f2a900'; // the site's warning yellow: reads on every filament colour

	let host: HTMLDivElement;
	let status = $state<'loading' | 'ready' | 'error'>('loading');
	let hasMesh = $state(false); // after the first load, a swap keeps the old part on screen

	// Literal black absorbs everything under any lighting model, so recesses
	// and edges vanish. Keep the hue; floor the luminance for display only.
	function legibleViewerColor(value: string): THREE.Color {
		const result = new THREE.Color(value);
		const hsl = { h: 0, s: 0, l: 0 };
		result.getHSL(hsl);
		if (hsl.l < 0.1) result.setHSL(hsl.h, hsl.s, 0.1);
		return result;
	}

	// The same face frame catalog/engrave.py used to lay the text out: v is as
	// close to +Z as the face allows (or +Y on a horizontal face), u = v x n.
	function markFrame(n: THREE.Vector3) {
		const up = Math.abs(n.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0);
		const v = up.clone().addScaledVector(n, -up.dot(n)).normalize();
		const u = new THREE.Vector3().crossVectors(v, n);
		return { u, v };
	}

	// Per-vertex colour: the part colour everywhere, the accent on every
	// triangle whose centroid sits inside the text's footprint and below the
	// face -- the pocket's floor and walls -- so the mark is visible at any
	// zoom without knowing anything about the glyphs. On a flat face "below"
	// is measured against the face's plane; on a wall, radially against the
	// cylinder or cone it sits on, since the wall itself curves away from any
	// plane by more than the pocket is deep.
	function paint(geo: THREE.BufferGeometry, stlCenter: THREE.Vector3, base: THREE.Color) {
		const pos = geo.getAttribute('position');
		const colors = new Float32Array(pos.count * 3);
		const accent = new THREE.Color(ACCENT);
		let m: { c: THREE.Vector3; n: THREE.Vector3; u: THREE.Vector3; v: THREE.Vector3; hw: number; hh: number } | null = null;
		let s: { a: THREE.Vector3; p: THREE.Vector3; r0: number; slope: number; sign: number; cos: number } | null = null;
		if (mark) {
			const n = new THREE.Vector3().fromArray(mark.normal).normalize();
			const { u, v } = markFrame(n);
			m = { c: new THREE.Vector3().fromArray(mark.center).sub(stlCenter), n, u, v, hw: mark.size[0] / 2 + 0.6, hh: mark.size[1] / 2 + 0.6 };
			if (mark.surface) {
				const sf = mark.surface;
				s = { a: new THREE.Vector3().fromArray(sf.axis).normalize(), p: new THREE.Vector3().fromArray(sf.point).sub(stlCenter), r0: sf.r0, slope: sf.slope, sign: sf.sign, cos: Math.cos(Math.atan(sf.slope)) };
			}
		}
		const p = new THREE.Vector3();
		const q = new THREE.Vector3();
		const r = new THREE.Vector3();
		for (let i = 0; i < pos.count; i += 3) {
			let hit = false;
			if (m) {
				p.set(0, 0, 0);
				for (let k = 0; k < 3; k++) p.add(q.fromBufferAttribute(pos, i + k));
				p.multiplyScalar(1 / 3);
				let below: number; // mm below the face, positive inside the pocket
				if (s) {
					r.copy(p).sub(s.p);
					const t = r.dot(s.a);
					const rad = r.addScaledVector(s.a, -t).length();
					below = s.sign * (s.r0 + s.slope * t - rad) * s.cos;
				} else {
					below = -p.clone().sub(m.c).dot(m.n);
				}
				p.sub(m.c);
				hit = below > 0.02 && below < 0.75 && Math.abs(p.dot(m.u)) <= m.hw && Math.abs(p.dot(m.v)) <= m.hh;
			}
			const col = hit ? accent : base;
			for (let k = 0; k < 3; k++) col.toArray(colors, (i + k) * 3);
		}
		geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
	}

	// --- scene state, created once on mount -------------------------------
	let scene: THREE.Scene;
	let camera: THREE.PerspectiveCamera;
	let controls: OrbitControls;
	let mesh: THREE.Mesh | undefined;
	let material: THREE.MeshStandardMaterial;
	let stlCenter = new THREE.Vector3();
	let radius = 100;
	let loadedUrl = '';
	let framed = false;

	// The orbit centre is always the part's centre, never the mark. "Show me"
	// flies the camera next to the mark and turns it to look there (`gaze`
	// overrides where the camera points each frame); the first drag hands the
	// view back to the orbit centre with a short blend, so rotating never pivots
	// around the engraving.
	let flight: { from: THREE.Vector3; to: THREE.Vector3; start: number } | null = null;
	let gaze: THREE.Vector3 | null = null;
	let gazeBlend: { from: THREE.Vector3; start: number } | null = null;
	function flyTo(position: THREE.Vector3, lookAt: THREE.Vector3 | null) {
		flight = { from: camera.position.clone(), to: position, start: performance.now() };
		gaze = lookAt;
		gazeBlend = null;
	}
	function homePose() {
		const dist = (radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.05;
		return new THREE.Vector3(1, 0.8, 1.3).normalize().multiplyScalar(dist);
	}

	export function resetView() {
		if (!camera) return;
		flyTo(homePose(), null);
	}
	export function viewMark() {
		if (!camera || !mesh || !mark) return;
		const at = mesh.localToWorld(new THREE.Vector3().fromArray(mark.center).sub(stlCenter));
		const n = new THREE.Vector3().fromArray(mark.normal).normalize().applyQuaternion(mesh.quaternion);
		// close enough to read 3.5 mm text, far enough to see which face it is on
		const view = Math.min(Math.max(radius * 0.6, 60), 160);
		const dist = view / (2 * Math.tan((camera.fov * Math.PI) / 360));
		flyTo(at.clone().addScaledVector(n, dist), at);
	}

	function load(u: string) {
		status = 'loading';
		new STLLoader().load(
			u,
			(geo) => {
				if (u !== url) return; // a later swap won
				geo.computeVertexNormals();
				geo.computeBoundingBox();
				stlCenter = geo.boundingBox!.getCenter(new THREE.Vector3());
				geo.center();
				paint(geo, stlCenter, legibleViewerColor(color));
				if (mesh) {
					mesh.geometry.dispose();
					mesh.geometry = geo;
				} else {
					mesh = new THREE.Mesh(geo, material);
					mesh.rotation.x = -Math.PI / 2; // STL is Z-up; the scene is Y-up
					scene.add(mesh);
					hasMesh = true;
				}
				geo.computeBoundingSphere();
				radius = geo.boundingSphere!.radius || 1;
				if (!framed) {
					camera.position.copy(homePose());
					controls.target.set(0, 0, 0);
					controls.update();
					framed = true;
				}
				loadedUrl = u;
				status = 'ready';
			},
			undefined,
			() => (status = 'error')
		);
	}

	// swap geometry when the url changes; repaint when the colour or mark does
	$effect(() => {
		const u = url;
		if (scene && u !== loadedUrl) load(u);
	});
	$effect(() => {
		const c = color;
		mark;
		if (mesh && loadedUrl === url) paint(mesh.geometry, stlCenter, legibleViewerColor(c));
	});

	onMount(() => {
		const el = host;
		scene = new THREE.Scene();
		scene.background = null;

		camera = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
		const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.toneMapping = THREE.NoToneMapping;
		renderer.domElement.style.display = 'block';
		renderer.domElement.style.width = '100%';
		renderer.domElement.style.height = '100%';
		el.appendChild(renderer.domElement);

		// CAD lighting: even ambient, one headlight slightly above the eye
		scene.add(new THREE.AmbientLight(0xffffff, 1.1));
		const headlight = new THREE.DirectionalLight(0xffffff, 1.9);
		headlight.position.set(0.25, 0.45, 1);
		camera.add(headlight);
		scene.add(camera);

		material = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0, roughness: 0.9 });

		controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		controls.addEventListener('start', () => {
			flight = null; // a drag cancels a flight
			if (gaze) {
				gazeBlend = { from: gaze, start: performance.now() }; // and hands the view back to the orbit centre
				gaze = null;
			}
		});

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

		load(url);

		let raf = 0;
		function loop() {
			if (flight) {
				const k = Math.min(1, (performance.now() - flight.start) / 550);
				const e = 1 - Math.pow(1 - k, 3);
				camera.position.lerpVectors(flight.from, flight.to, e);
				if (k >= 1) flight = null;
			}
			controls.update(); // points the camera at the orbit centre (the part)
			if (gaze) camera.lookAt(gaze);
			else if (gazeBlend) {
				const k = Math.min(1, (performance.now() - gazeBlend.start) / 300);
				camera.lookAt(new THREE.Vector3().lerpVectors(gazeBlend.from, controls.target, k));
				if (k >= 1) gazeBlend = null;
			}
			renderer.render(scene, camera);
			raf = requestAnimationFrame(loop);
		}
		loop();

		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			controls.dispose();
			renderer.dispose();
			mesh?.geometry.dispose();
			material.dispose();
			renderer.domElement.remove();
		};
	});
</script>

<div class="relative {heightClass} w-full bg-[var(--color-bg)]">
	<div bind:this={host} class="h-full w-full"></div>
	{#if status === 'error'}
		<div class="absolute inset-0 flex items-center justify-center text-sm text-text-muted">Could not load model.</div>
	{:else if status === 'loading' && !hasMesh}
		<div class="absolute inset-0 flex items-center justify-center text-sm text-text-muted">Loading 3D model…</div>
	{/if}
	<div class="pointer-events-none absolute bottom-2 left-3 text-xs text-text-muted">drag to rotate · scroll to zoom</div>
</div>
