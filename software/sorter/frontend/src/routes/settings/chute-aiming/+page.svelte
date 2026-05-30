<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { Alert, Button, Input } from '$lib/components/primitives';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	const FINE = 0.25;
	const COARSE = 2;

	// ---- Canonical aiming geometry (mirrors backend chute.py) --------------
	// bin_center = θ0 + section·(360/N) + (i + 0.5)·(W / K)
	let numSections = $state(6);
	let sectionWidthDeg = $state(51.75);
	let firstSectionOffsetDeg = $state(8.25);
	let maxAngleDeg = $state(350);

	const sectionPitchDeg = $derived(numSections > 0 ? 360 / numSections : 60);
	const pillarWidthDeg = $derived(sectionPitchDeg - sectionWidthDeg);

	// ---- Live status -------------------------------------------------------
	let liveAvailable = $state(false);
	let currentAngle = $state<number | null>(null);
	let stepperStopped = $state<boolean | null>(null);
	let liveRequestInFlight = false;

	// ---- Calibration measurement -------------------------------------------
	let homed = $state(false);
	let binsInTestSection = $state(3);
	let capturedFirst = $state<number | null>(null);
	let capturedLast = $state<number | null>(null);
	let calibrationLabel = $state('');

	// ---- History -----------------------------------------------------------
	type Calibration = {
		id: string;
		created_at: number;
		label: string | null;
		num_sections: number;
		section_width_deg: number;
		first_section_offset_deg: number;
		is_active: boolean;
	};
	let calibrations = $state<Calibration[]>([]);

	// ---- UI state ----------------------------------------------------------
	let loadedMachineKey = $state('');
	let editingParams = $state(false);
	let busy = $state(false); // a chute-moving action is in flight
	let movingJog = false; // guards arrow-key repeat flooding
	let homingState = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');

	// Vertical wizard gating — each step unlocks on the previous step's data.
	const activeStep = $derived(
		!homed ? 1 : capturedFirst === null ? 2 : capturedLast === null ? 3 : 4
	);
	const step2Locked = $derived(!homed);
	const step3Locked = $derived(capturedFirst === null);
	const step4Locked = $derived(capturedFirst === null || capturedLast === null);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function fmt(v: number | null | undefined, d = 1): string {
		return v === null || v === undefined || !Number.isFinite(v) ? '--' : v.toFixed(d);
	}
	function fmtDate(epoch: number): string {
		try {
			return new Date(epoch * 1000).toLocaleString();
		} catch {
			return '--';
		}
	}

	function angleFor(section: number, bin: number, binsInSection: number): number {
		const k = Math.max(1, binsInSection);
		const slot = sectionWidthDeg / k;
		return firstSectionOffsetDeg + section * (360 / Math.max(1, numSections)) + (bin + 0.5) * slot;
	}
	function isReachable(angle: number): boolean {
		return angle >= 0 && angle <= maxAngleDeg && angle <= 360;
	}

	async function loadSettings() {
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute`);
			if (!res.ok) throw new Error(await res.text());
			const c = await res.json();
			if (Number.isFinite(c?.num_sections)) numSections = c.num_sections;
			if (Number.isFinite(c?.section_width_deg)) sectionWidthDeg = c.section_width_deg;
			if (Number.isFinite(c?.first_section_offset_deg)) firstSectionOffsetDeg = c.first_section_offset_deg;
			if (Number.isFinite(c?.max_angle_deg)) maxAngleDeg = c.max_angle_deg;
			void loadCalibrations();
			void loadLive();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load chute aiming settings';
		}
	}

	async function loadCalibrations() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute/calibrations`);
			if (!res.ok) return;
			const p = await res.json();
			if (Array.isArray(p?.calibrations)) calibrations = p.calibrations;
		} catch {
			// non-critical
		}
	}

	async function loadLive() {
		if (liveRequestInFlight) return;
		liveRequestInFlight = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute/live`);
			if (!res.ok) throw new Error(await res.text());
			const p = await res.json();
			liveAvailable = Boolean(p?.live_available);
			currentAngle =
				typeof p?.current_angle === 'number' && Number.isFinite(p.current_angle) ? p.current_angle : null;
			stepperStopped = typeof p?.stepper_stopped === 'boolean' ? p.stepper_stopped : null;
		} catch {
			// keep last known
		} finally {
			liveRequestInFlight = false;
		}
	}

	function applyResult(payload: any) {
		const s = payload?.settings;
		if (s) {
			if (Number.isFinite(s.num_sections)) numSections = s.num_sections;
			if (Number.isFinite(s.section_width_deg)) sectionWidthDeg = s.section_width_deg;
			if (Number.isFinite(s.first_section_offset_deg)) firstSectionOffsetDeg = s.first_section_offset_deg;
		}
		if (Array.isArray(payload?.calibrations)) calibrations = payload.calibrations;
		statusMsg = payload?.message ?? statusMsg;
	}

	async function post(path: string, body?: unknown): Promise<any> {
		const res = await fetch(`${currentBackendBaseUrl()}${path}`, {
			method: 'POST',
			headers: body ? { 'Content-Type': 'application/json' } : undefined,
			body: body ? JSON.stringify(body) : undefined
		});
		if (!res.ok) throw new Error(await res.text());
		return res.json();
	}

	async function saveParams() {
		busy = true;
		errorMsg = null;
		statusMsg = '';
		try {
			applyResult(
				await post('/api/hardware-config/chute/aiming', {
					num_sections: numSections,
					section_width_deg: sectionWidthDeg,
					first_section_offset_deg: firstSectionOffsetDeg,
					label: 'Manual edit'
				})
			);
			editingParams = false;
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save parameters';
		} finally {
			busy = false;
		}
	}

	async function homeChute() {
		homingState = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const p = await post('/api/hardware-config/chute/calibrate/find-endstop');
			homed = true;
			statusMsg = p?.message ?? 'Chute homed to its endstop.';
			void loadLive();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to home the chute';
		} finally {
			homingState = false;
		}
	}

	async function cancelHome() {
		try {
			await post('/api/hardware-config/chute/calibrate/cancel');
			statusMsg = 'Chute homing canceled.';
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to cancel homing';
		}
	}

	async function jogTo(angle: number) {
		if (movingJog) return;
		movingJog = true;
		busy = true;
		errorMsg = null;
		try {
			const p = await post('/api/hardware-config/chute/move-to-angle', { angle });
			currentAngle = typeof p?.target_angle === 'number' ? p.target_angle : currentAngle;
			void loadLive();
		} catch (e: any) {
			errorMsg = e.message ?? 'Chute move failed';
		} finally {
			movingJog = false;
			busy = false;
		}
	}
	function nudge(delta: number) {
		const base = currentAngle ?? 0;
		void jogTo(Math.max(0, Math.min(360, Number((base + delta).toFixed(3)))));
	}

	function captureFirst() {
		if (currentAngle !== null) capturedFirst = Number(currentAngle.toFixed(2));
	}
	function captureLast() {
		if (currentAngle !== null) capturedLast = Number(currentAngle.toFixed(2));
	}
	function resetCalibration() {
		homed = false;
		capturedFirst = null;
		capturedLast = null;
		calibrationLabel = '';
	}

	async function deriveAndLockIn() {
		if (capturedFirst === null || capturedLast === null) return;
		busy = true;
		errorMsg = null;
		statusMsg = '';
		try {
			applyResult(
				await post('/api/hardware-config/chute/aiming/derive', {
					first_bin_angle: capturedFirst,
					last_bin_angle: capturedLast,
					bins_in_test_section: binsInTestSection,
					num_sections: numSections,
					label: calibrationLabel.trim() || null
				})
			);
			resetCalibration();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to derive aiming geometry';
		} finally {
			busy = false;
		}
	}

	async function lockIn(id: string) {
		busy = true;
		errorMsg = null;
		statusMsg = '';
		try {
			applyResult(await post(`/api/hardware-config/chute/calibrations/${id}/activate`));
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to lock in calibration';
		} finally {
			busy = false;
		}
	}

	async function deleteCalibration(id: string) {
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/hardware-config/chute/calibrations/${id}`, {
				method: 'DELETE'
			});
			if (!res.ok) throw new Error(await res.text());
			const p = await res.json();
			if (Array.isArray(p?.calibrations)) calibrations = p.calibrations;
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to delete calibration';
		}
	}

	// ---- Test aim ----------------------------------------------------------
	let testBinsPerSection = $state(3);
	let selected = $state<{ section: number; bin: number } | null>(null);

	async function testAimSelected() {
		if (!selected) return;
		busy = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const p = await post('/api/hardware-config/chute/move-to-virtual-bin', {
				num_sections: numSections,
				bins_in_section: testBinsPerSection,
				section_index: selected.section,
				bin_index: selected.bin
			});
			statusMsg = `Aiming at section ${selected.section + 1}, bin ${selected.bin + 1} (${fmt(p?.target_angle)}°).`;
			void loadLive();
		} catch (e: any) {
			errorMsg = e.message ?? 'Test aim failed';
		} finally {
			busy = false;
		}
	}

	// ---- Keyboard jog (only while a jog step is the active wizard step) -----
	function handleKey(e: KeyboardEvent) {
		if (activeStep !== 2 && activeStep !== 3) return;
		const el = document.activeElement;
		if (el instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return;
		let delta = 0;
		if (e.key === 'ArrowUp') delta = FINE;
		else if (e.key === 'ArrowDown') delta = -FINE;
		else if (e.key === 'ArrowLeft') delta = -COARSE;
		else if (e.key === 'ArrowRight') delta = COARSE;
		else return;
		e.preventDefault();
		nudge(delta);
	}

	$effect(() => {
		const machineKey =
			(manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null) ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadSettings();
		}
	});

	onMount(() => {
		const interval = setInterval(() => void loadLive(), 600);
		return () => clearInterval(interval);
	});

	// ---- SVG geometry for the test circle ----------------------------------
	const CX = 130;
	const CY = 130;
	const R = 96;
	function polar(angleDeg: number, radius = R) {
		const rad = ((angleDeg - 90) * Math.PI) / 180;
		return { x: CX + radius * Math.cos(rad), y: CY + radius * Math.sin(rad) };
	}
	const vizBins = $derived(
		Array.from({ length: numSections }, (_, s) =>
			Array.from({ length: testBinsPerSection }, (_, i) => {
				const angle = angleFor(s, i, testBinsPerSection);
				return { section: s, bin: i, angle, reachable: isReachable(angle), ...polar(angle) };
			})
		).flat()
	);
	const needle = $derived(currentAngle === null ? null : polar(currentAngle));
	const homeMarker = $derived(polar(0, R + 10));
</script>

<svelte:window onkeydown={handleKey} />

{#snippet jogKey(glyph: string, label: string, delta: number, active: boolean)}
	<button
		class="flex flex-col items-center border border-border bg-surface px-3 py-1.5 text-text hover:bg-bg active:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
		disabled={!active || busy}
		onclick={() => nudge(delta)}
	>
		<span class="text-base leading-none">{glyph}</span>
		<span class="text-xs text-text-muted">{label}</span>
	</button>
{/snippet}

{#snippet jogPad(active: boolean, showBins: boolean)}
	<div class="flex w-fit border border-border bg-bg">
		<!-- Left: jog the chute -->
		<div class="flex flex-col gap-2 p-3" class:opacity-40={!active}>
			<div class="text-sm font-medium text-text">Jog the chute</div>
			<div class="grid grid-cols-3 gap-1 select-none">
				<div></div>
				{@render jogKey('↑', `+${FINE}°`, FINE, active)}
				<div></div>

				{@render jogKey('←', `−${COARSE}°`, -COARSE, active)}
				<div class="flex flex-col items-center justify-center border border-border bg-surface px-2 py-1.5">
					<span class="text-sm font-semibold text-text">{fmt(currentAngle, 2)}°</span>
					<span class="text-xs text-text-muted">current</span>
				</div>
				{@render jogKey('→', `+${COARSE}°`, COARSE, active)}

				<div></div>
				{@render jogKey('↓', `−${FINE}°`, -FINE, active)}
				<div></div>
			</div>
			{#if active}
				<p class="max-w-[15rem] text-sm text-text-muted">
					Arrow keys work too: ↑ ↓ fine {FINE}°, ← → coarse {COARSE}°. Hold to repeat.
				</p>
			{/if}
		</div>

		{#if showBins}
			<!-- Divider down the middle, then: how many bins -->
			<div class="flex flex-col gap-2 border-l border-border p-3">
				<div class="text-sm font-medium text-text">Bins in this section</div>
				<div class="grid grid-cols-3 gap-1">
					{#each [1, 2, 3, 4, 5, 6] as n}
						<Button
							variant={binsInTestSection === n ? 'primary' : 'secondary'}
							size="sm"
							onclick={() => (binsInTestSection = n)}
						>
							{n}
						</Button>
					{/each}
				</div>
				<p class="max-w-[13rem] text-sm text-text-muted">
					How many bins evenly divide the section you're measuring.
				</p>
			</div>
		{/if}
	</div>
{/snippet}

{#snippet stepBadge(n: number, done: boolean)}
	<span
		class={`flex h-6 w-6 shrink-0 items-center justify-center text-sm font-semibold ${
			done
				? 'bg-success text-primary-contrast'
				: activeStep === n
					? 'bg-primary text-primary-contrast'
					: 'border border-border bg-surface text-text-muted'
		}`}
	>
		{done ? '✓' : n}
	</span>
{/snippet}

<div class="flex max-w-4xl flex-col gap-5">
	<div class="flex flex-col gap-1">
		<h1 class="text-lg font-semibold text-text">Chute Aiming</h1>
		<p class="text-sm text-text-muted">
			If the chute points at the wrong bin, run the calibration below. If you didn't come here for
			that, the defaults are already correct — you can leave this page.
		</p>
	</div>

	{#if errorMsg}
		<Alert variant="danger">{errorMsg}</Alert>
	{:else if statusMsg}
		<Alert variant="info">{statusMsg}</Alert>
	{/if}

	<!-- Active parameters — forefront, edit hidden behind hover -->
	<section class="group flex flex-col gap-3 border border-border bg-bg px-4 py-3">
		<div class="flex items-center justify-between">
			<div class="text-sm font-semibold text-text">Active aiming parameters</div>
			{#if !editingParams}
				<button
					class="text-sm text-text-muted underline opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 hover:text-text"
					onclick={() => (editingParams = true)}
				>
					Edit manually
				</button>
			{/if}
		</div>

		{#if !editingParams}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-5">
				<div>
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Sections</div>
					<div class="text-sm font-medium text-text">{numSections}</div>
				</div>
				<div>
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Section W</div>
					<div class="text-sm font-medium text-text">{fmt(sectionWidthDeg, 2)}°</div>
				</div>
				<div>
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Offset θ₀</div>
					<div class="text-sm font-medium text-text">{fmt(firstSectionOffsetDeg, 2)}°</div>
				</div>
				<div>
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Pitch</div>
					<div class="text-sm font-medium text-text">{fmt(sectionPitchDeg, 2)}°</div>
				</div>
				<div>
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Pillar</div>
					<div class="text-sm font-medium text-text">{fmt(pillarWidthDeg, 2)}°</div>
				</div>
			</div>
		{:else}
			<Alert variant="warning">
				These are produced by the calibration routine. Only edit by hand if you know exactly what
				these numbers mean.
			</Alert>
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
				<label class="flex flex-col gap-1 text-sm text-text">
					Sections (N)
					<Input type="number" bind:value={numSections} />
				</label>
				<label class="flex flex-col gap-1 text-sm text-text">
					Section width W (°)
					<Input type="number" bind:value={sectionWidthDeg} />
				</label>
				<label class="flex flex-col gap-1 text-sm text-text">
					Offset θ₀ (°)
					<Input type="number" bind:value={firstSectionOffsetDeg} />
				</label>
			</div>
			<div class="flex gap-2">
				<Button variant="primary" loading={busy} onclick={saveParams}>Save manual values</Button>
				<Button variant="ghost" onclick={() => { editingParams = false; void loadSettings(); }}>
					Cancel
				</Button>
			</div>
		{/if}
	</section>

	<!-- Calibration wizard -->
	<section class="flex flex-col gap-3">
		<div class="flex items-center justify-between">
			<h2 class="text-base font-semibold text-text">Run calibration</h2>
			{#if homed || capturedFirst !== null || capturedLast !== null}
				<button class="text-sm text-text-muted underline hover:text-text" onclick={resetCalibration}>
					Start over
				</button>
			{/if}
		</div>

		<Alert variant="warning">
			Every step here moves the chute. It hits a hard stop at 0° and 360° and can never cross zero —
			always home first.
		</Alert>

		<!-- Step 1: Home -->
		<div class="flex flex-col gap-3 border border-border bg-bg px-4 py-3">
			<div class="flex items-center gap-2">
				{@render stepBadge(1, homed)}
				<div class="text-sm font-medium text-text">Home the chute</div>
			</div>
			<p class="text-sm text-text-muted">Establishes the 0° reference at the home switch.</p>
			<div class="flex flex-wrap items-center gap-2">
				<Button variant={homed ? 'secondary' : 'primary'} loading={homingState} onclick={homeChute}>
					{homed ? 'Re-home' : 'Home chute'}
				</Button>
				{#if homingState}
					<Button variant="danger" onclick={cancelHome}>Cancel</Button>
				{/if}
				{#if homed}<span class="text-sm text-success">Homed.</span>{/if}
			</div>
		</div>

		<!-- Step 2: First bin -->
		<div
			class="flex flex-col gap-3 border border-border bg-bg px-4 py-3"
			class:opacity-50={step2Locked}
			class:pointer-events-none={step2Locked}
		>
			<div class="flex items-center gap-2">
				{@render stepBadge(2, capturedFirst !== null)}
				<div class="text-sm font-medium text-text">Aim at the FIRST bin of a section</div>
			</div>
			<p class="text-sm text-text-muted">
				{#if step2Locked}Home the chute first.{:else}Jog until the chute points dead-center at the first bin, then capture.{/if}
			</p>
			{@render jogPad(activeStep === 2, false)}
			<div class="flex flex-wrap items-center gap-2">
				<Button variant="primary" disabled={step2Locked || currentAngle === null} onclick={captureFirst}>
					Capture first bin
				</Button>
				<span class="text-sm text-text-muted">Captured: {fmt(capturedFirst, 2)}°</span>
			</div>
		</div>

		<!-- Step 3: Last bin -->
		<div
			class="flex flex-col gap-3 border border-border bg-bg px-4 py-3"
			class:opacity-50={step3Locked}
			class:pointer-events-none={step3Locked}
		>
			<div class="flex items-center gap-2">
				{@render stepBadge(3, capturedLast !== null)}
				<div class="text-sm font-medium text-text">Aim at the LAST bin of that same section</div>
			</div>
			<p class="text-sm text-text-muted">
				{#if step3Locked}Capture the first bin first.{:else}Pick how many bins the section has, jog to its last bin, then capture.{/if}
			</p>
			{@render jogPad(activeStep === 3, true)}
			<div class="flex flex-wrap items-center gap-3">
				<Button variant="primary" disabled={step3Locked || currentAngle === null} onclick={captureLast}>
					Capture last bin
				</Button>
				<span class="text-sm text-text-muted">Captured: {fmt(capturedLast, 2)}°</span>
			</div>
		</div>

		<!-- Step 4: Review + lock in -->
		<div
			class="flex flex-col gap-3 border border-border bg-bg px-4 py-3"
			class:opacity-50={step4Locked}
			class:pointer-events-none={step4Locked}
		>
			<div class="flex items-center gap-2">
				{@render stepBadge(4, false)}
				<div class="text-sm font-medium text-text">Lock in</div>
			</div>
			{#if !step4Locked}
				{@const slot = (capturedLast! - capturedFirst!) / Math.max(1, binsInTestSection - 1)}
				{@const w = slot * binsInTestSection}
				<div class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
					<div><span class="text-text-muted">Section width W:</span> {fmt(w, 2)}°</div>
					<div><span class="text-text-muted">Offset θ₀:</span> {fmt(capturedFirst! - 0.5 * slot, 2)}°</div>
					<div><span class="text-text-muted">Pillar:</span> {fmt(sectionPitchDeg - w, 2)}°</div>
				</div>
				<label class="flex max-w-sm flex-col gap-1 text-sm text-text">
					Label (optional)
					<Input type="text" bind:value={calibrationLabel} placeholder="e.g. after home-switch move" />
				</label>
			{:else}
				<p class="text-sm text-text-muted">Capture both bins to compute and lock in the geometry.</p>
			{/if}
			<div>
				<Button variant="primary" loading={busy} disabled={step4Locked} onclick={deriveAndLockIn}>
					Derive &amp; lock in
				</Button>
			</div>
		</div>
	</section>

	<!-- History -->
	<section class="flex flex-col gap-3 border border-border bg-bg px-4 py-3">
		<div class="text-sm font-semibold text-text">Saved calibrations</div>
		{#if calibrations.length === 0}
			<p class="text-sm text-text-muted">No saved calibrations yet. Run the routine above to create one.</p>
		{:else}
			<div class="flex flex-col">
				{#each calibrations as cal (cal.id)}
					<div class="flex items-center justify-between gap-3 border-b border-border py-2 last:border-b-0">
						<div class="min-w-0">
							<div class="flex items-center gap-2 text-sm text-text">
								<span class="truncate font-medium">{cal.label ?? 'Calibration'}</span>
								{#if cal.is_active}
									<span class="bg-success px-1.5 py-0.5 text-xs font-semibold text-primary-contrast">ACTIVE</span>
								{/if}
							</div>
							<div class="text-sm text-text-muted">
								{fmtDate(cal.created_at)} · N{cal.num_sections} · W{fmt(cal.section_width_deg, 1)}° · θ₀{fmt(cal.first_section_offset_deg, 1)}°
							</div>
						</div>
						<div class="flex shrink-0 items-center gap-2">
							{#if !cal.is_active}
								<Button variant="secondary" size="sm" loading={busy} onclick={() => lockIn(cal.id)}>
									Lock in
								</Button>
								<Button variant="ghost" size="sm" onclick={() => deleteCalibration(cal.id)}>Delete</Button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</section>

	<!-- Verify -->
	<section class="flex flex-col gap-3 border border-border bg-bg px-4 py-3">
		<div class="text-sm font-semibold text-text">Verify aim</div>
		<p class="text-sm text-text-muted">Pick a layout, click a bin, then test-aim to confirm reality matches.</p>
		<div class="flex flex-wrap items-center gap-1">
			<span class="mr-1 text-sm text-text-muted">Bins per section:</span>
			{#each [1, 2, 3, 4, 5, 6] as preset}
				<Button
					variant={testBinsPerSection === preset ? 'primary' : 'secondary'}
					size="sm"
					onclick={() => { testBinsPerSection = preset; selected = null; }}
				>
					{preset}
				</Button>
			{/each}
		</div>
		<div class="flex flex-col items-start gap-4 sm:flex-row">
			<svg viewBox="0 0 260 260" class="w-64 max-w-full" role="img" aria-label="Bin layout circle">
				<circle cx={CX} cy={CY} r={R} class="fill-surface stroke-border" stroke-width="1" />
				{#each Array.from({ length: numSections }, (_, s) => firstSectionOffsetDeg + s * sectionPitchDeg) as edge}
					{@const p = polar(edge, R + 6)}
					<line x1={CX} y1={CY} x2={p.x} y2={p.y} class="stroke-border" stroke-width="0.5" />
				{/each}
				<circle cx={homeMarker.x} cy={homeMarker.y} r="3" class="fill-primary" />
				<text x={homeMarker.x} y={homeMarker.y - 6} text-anchor="middle" font-size="10" class="fill-text-muted">home 0°</text>
				{#if needle}
					<line x1={CX} y1={CY} x2={needle.x} y2={needle.y} class="stroke-primary" stroke-width="1.5" />
				{/if}
				{#each vizBins as b}
					{@const isSel = selected?.section === b.section && selected?.bin === b.bin}
					<circle
						cx={b.x}
						cy={b.y}
						r={isSel ? 7 : 5}
						class={`cursor-pointer ${!b.reachable ? 'fill-danger stroke-danger' : isSel ? 'fill-primary stroke-primary' : 'fill-bg stroke-text-muted'}`}
						stroke-width="1"
						role="button"
						tabindex="0"
						onclick={() => (selected = { section: b.section, bin: b.bin })}
						onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selected = { section: b.section, bin: b.bin }; }}
					/>
				{/each}
				<circle cx={CX} cy={CY} r="2" class="fill-text-muted" />
			</svg>
			<div class="flex min-w-0 flex-1 flex-col gap-2">
				{#if selected}
					<div class="text-sm text-text">
						Selected: section {selected.section + 1}, bin {selected.bin + 1}
						<span class="text-text-muted">→ {fmt(angleFor(selected.section, selected.bin, testBinsPerSection), 2)}°</span>
					</div>
					<div>
						<Button
							variant="primary"
							loading={busy}
							disabled={!isReachable(angleFor(selected.section, selected.bin, testBinsPerSection))}
							onclick={testAimSelected}
						>
							Test aim at this bin
						</Button>
					</div>
				{:else}
					<div class="text-sm text-text-muted">Click a bin in the circle to select it.</div>
				{/if}
			</div>
		</div>
	</section>
</div>
