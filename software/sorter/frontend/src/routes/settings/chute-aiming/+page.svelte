<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Check from '@lucide/svelte/icons/check';
	import BinLayoutViz from './BinLayoutViz.svelte';
	import ErrorBanner from './ErrorBanner.svelte';
	import { binCenterAngle, reachInfo } from '$lib/chute/geometry';

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
	let liveEndstopTriggered = $state<boolean | null>(null);
	let stepperPositionDeg = $state<number | null>(null);
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
		return binCenterAngle(
			{ numSections, sectionWidthDeg, firstSectionOffsetDeg },
			section,
			bin,
			binsInSection
		);
	}
	function isReachable(angle: number): boolean {
		return reachInfo(angle, maxAngleDeg).reachable;
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
			liveEndstopTriggered = typeof p?.endstop_triggered === 'boolean' ? p.endstop_triggered : null;
			stepperPositionDeg =
				typeof p?.stepper_position_degrees === 'number' && Number.isFinite(p.stepper_position_degrees)
					? p.stepper_position_degrees
					: null;
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
	// One viz instance per layer size so all are visible at once, instead of a
	// single circle you toggle between 1–5 bins.
	const VIZ_SIZES = [1, 2, 3, 4, 5];
	let selected = $state<{ section: number; bin: number; binCount: number } | null>(null);

	async function testAimSelected() {
		if (!selected) return;
		busy = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const p = await post('/api/hardware-config/chute/move-to-virtual-bin', {
				num_sections: numSections,
				bins_in_section: selected.binCount,
				section_index: selected.section,
				bin_index: selected.bin
			});
			statusMsg = `Aiming at ${selected.binCount}-bin section ${selected.section + 1}, bin ${selected.bin + 1} (${fmt(p?.target_angle)}°).`;
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

	// Poll live status; speed up while homing so you can watch the chute drive
	// to 0° and back off to the first bin. Kept modest so it never floods.
	$effect(() => {
		const period = homingState ? 200 : 600;
		const interval = setInterval(() => void loadLive(), period);
		return () => clearInterval(interval);
	});

</script>

<svelte:head><title>Sorter - Chute aiming</title></svelte:head>

<svelte:window onkeydown={handleKey} />

{#snippet jogKey(icon: typeof ArrowUp, label: string, delta: number, active: boolean)}
	<Button variant="secondary" size="sm" {icon} disabled={!active || busy} onclick={() => nudge(delta)}>
		{label}
	</Button>
{/snippet}

{#snippet jogPad(active: boolean, showBins: boolean)}
	<div class="flex w-fit flex-wrap gap-x-8 gap-y-4 rounded-control bg-well p-3">
		<div class="flex flex-col gap-2" class:opacity-40={!active}>
			<span class="label">Jog the chute</span>
			<div class="grid grid-cols-3 gap-1 select-none">
				<span></span>
				{@render jogKey(ArrowUp, `+${FINE}°`, FINE, active)}
				<span></span>
				{@render jogKey(ArrowLeft, `−${COARSE}°`, -COARSE, active)}
				<span class="flex flex-col items-center justify-center rounded-control bg-surface px-2 py-1">
					<span class="num text-sm font-medium text-ink">{fmt(currentAngle, 2)}°</span>
					<span class="text-xs text-ink-muted">Now</span>
				</span>
				{@render jogKey(ArrowRight, `+${COARSE}°`, COARSE, active)}
				<span></span>
				{@render jogKey(ArrowDown, `−${FINE}°`, -FINE, active)}
				<span></span>
			</div>
			{#if active}
				<p class="max-w-60 text-sm text-ink-muted">
					The arrow keys work too: up and down move {FINE}°, left and right {COARSE}°. Hold one to
					repeat.
				</p>
			{/if}
		</div>
		{#if showBins}
			<div class="flex flex-col gap-2">
				<span class="label">Bins in this section</span>
				<SegmentedControl
					label="Bins in this section"
					size="sm"
					value={String(binsInTestSection)}
					options={['3', '4', '5', '6'].map((n) => ({ value: n, label: n }))}
					onchange={(n) => (binsInTestSection = Number(n))}
				/>
				<p class="max-w-52 text-sm text-ink-muted">
					How many bins the section you are measuring has. More is more accurate; 3 or 5 is best.
				</p>
			</div>
		{/if}
	</div>
{/snippet}

{#snippet stepHead(n: number, done: boolean, title: string)}
	<div class="flex items-center gap-2">
		<span
			class="flex size-6 shrink-0 items-center justify-center rounded-badge text-sm font-medium {done
				? 'bg-success-soft text-success-ink'
				: activeStep === n
					? 'bg-primary-soft text-primary-ink'
					: 'bg-well text-ink-muted'}"
		>
			{#if done}<Check size={14} />{:else}{n}{/if}
		</span>
		<h3 class="text-sm font-medium text-ink">{title}</h3>
	</div>
{/snippet}

{#snippet editFooter()}
	<Button
		variant="ghost"
		onclick={() => {
			editingParams = false;
			void loadSettings();
		}}
	>
		Cancel
	</Button>
	<Button variant="primary" loading={busy} onclick={saveParams}>Save</Button>
{/snippet}

<div class="flex max-w-4xl flex-col gap-(--gap-panels)">
	<PageHeader
		title="Chute aiming"
		description="If the chute points at the wrong bin, run the calibration below. Otherwise the defaults are already right and you can leave this page."
	/>

	{#if errorMsg}
		<ErrorBanner message={errorMsg} />
	{:else if statusMsg}
		<Alert tone="info">{statusMsg}</Alert>
	{/if}

	<!-- The active parameters come first; editing them by hand hides until hovered. -->
	<Panel
		title="Active aiming parameters"
		flush={!editingParams}
		class="group"
		footer={editingParams ? editFooter : undefined}
	>
		{#snippet actions()}
			{#if !editingParams}
				<Button
					variant="ghost"
					size="sm"
					class="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
					onclick={() => (editingParams = true)}
				>
					Edit by hand
				</Button>
			{/if}
		{/snippet}
		{#if !editingParams}
			<div class="grid grid-cols-2 gap-px bg-line sm:grid-cols-5">
				{#each [['Sections', String(numSections)], ['Section width', `${fmt(sectionWidthDeg, 2)}°`], ['Offset from home', `${fmt(firstSectionOffsetDeg, 2)}°`], ['Pitch', `${fmt(sectionPitchDeg, 2)}°`], ['Pillar', `${fmt(pillarWidthDeg, 2)}°`]] as [label, value] (label)}
					<div class="bg-surface max-sm:last:col-span-2"><Stat {label} {value} /></div>
				{/each}
			</div>
		{:else}
			<div class="flex flex-col gap-4">
				<Alert tone="warning">
					The calibration sets these. Only change them by hand if you know exactly what they mean.
				</Alert>
				<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
					<Field label="Sections (N)" for="aim-sections">
						<Input id="aim-sections" type="number" bind:value={numSections} />
					</Field>
					<Field label="Section width (W)" for="aim-width">
						<Input id="aim-width" type="number" unit="°" bind:value={sectionWidthDeg} />
					</Field>
					<Field label="Offset (θ₀)" for="aim-offset">
						<Input id="aim-offset" type="number" unit="°" bind:value={firstSectionOffsetDeg} />
					</Field>
				</div>
			</div>
		{/if}
	</Panel>

	<Panel
		title="Run the calibration"
		description="It finds two numbers: the width of a section in degrees, and the offset of the first section from home. From those the machine works out where every bin sits and which ones each layout can reach."
		flush
	>
		{#snippet actions()}
			{#if homed || capturedFirst !== null || capturedLast !== null}
				<Button variant="ghost" size="sm" onclick={resetCalibration}>Start over</Button>
			{/if}
		{/snippet}
		<div class="px-(--pad-panel) pb-4">
			<Alert tone="warning">
				Every step here moves the chute. It hits a hard stop at home and can never cross it, so it has
				about {fmt(maxAngleDeg, 0)}° of travel. Always home first.
			</Alert>
		</div>
		<ol class="divide-y divide-line border-t border-line">
			<li class="flex flex-col gap-3 px-(--pad-panel) py-4">
				{@render stepHead(1, homed, 'Home the chute')}
				<p class="text-sm text-ink-muted">Sets 0° at the home switch.</p>
				<dl class="flex w-fit flex-wrap gap-x-6 gap-y-1 rounded-control bg-well px-3 py-2 text-sm">
					<div class="flex gap-2">
						<dt class="text-ink-muted">Chute angle</dt>
						<dd class="num font-medium text-ink">{fmt(currentAngle, 1)}°</dd>
					</div>
					<div class="flex gap-2">
						<dt class="text-ink-muted">Motor angle</dt>
						<dd class="num font-medium text-ink">{fmt(stepperPositionDeg, 1)}°</dd>
					</div>
					<div class="flex gap-2">
						<dt class="text-ink-muted">Endstop</dt>
						<dd class="font-medium {liveEndstopTriggered ? 'text-success-ink' : 'text-ink'}">
							{liveEndstopTriggered === null ? '–' : liveEndstopTriggered ? 'Triggered' : 'Open'}
						</dd>
					</div>
				</dl>
				<div class="flex flex-wrap items-center gap-2">
					<Button variant={homed ? 'secondary' : 'primary'} loading={homingState} onclick={homeChute}>
						{homed ? 'Home again' : 'Home the chute'}
					</Button>
					{#if homingState}<Button variant="danger" onclick={cancelHome}>Cancel</Button>{/if}
					{#if homed}<span class="text-sm text-success-ink">Homed.</span>{/if}
				</div>
			</li>

			<li
				class="flex flex-col gap-3 px-(--pad-panel) py-4"
				class:opacity-50={step2Locked}
				class:pointer-events-none={step2Locked}
			>
				{@render stepHead(2, capturedFirst !== null, 'Aim at the first bin of a section')}
				<p class="text-sm text-ink-muted">
					{#if step2Locked}
						Home the chute first.
					{:else}
						Pick any layer, and a section you can see whole with more than 2 bins; 3 or 5 is best,
						and more bins is more accurate. Set its bin count, then jog until the chute points
						straight into the first bin, and capture.
					{/if}
				</p>
				{@render jogPad(activeStep === 2, true)}
				<div class="flex flex-wrap items-center gap-3">
					<Button variant="primary" disabled={step2Locked || currentAngle === null} onclick={captureFirst}>
						Capture the first bin
					</Button>
					<span class="num text-sm text-ink-muted">Captured {fmt(capturedFirst, 2)}°</span>
				</div>
			</li>

			<li
				class="flex flex-col gap-3 px-(--pad-panel) py-4"
				class:opacity-50={step3Locked}
				class:pointer-events-none={step3Locked}
			>
				{@render stepHead(3, capturedLast !== null, 'Aim at the last bin of that section')}
				<p class="text-sm text-ink-muted">
					{#if step3Locked}
						Capture the first bin first.
					{:else}
						Jog until the chute points straight into the last bin of the same section, then capture.
					{/if}
				</p>
				{@render jogPad(activeStep === 3, false)}
				<div class="flex flex-wrap items-center gap-3">
					<Button variant="primary" disabled={step3Locked || currentAngle === null} onclick={captureLast}>
						Capture the last bin
					</Button>
					<span class="num text-sm text-ink-muted">Captured {fmt(capturedLast, 2)}°</span>
				</div>
			</li>

			<li
				class="flex flex-col gap-3 px-(--pad-panel) py-4"
				class:opacity-50={step4Locked}
				class:pointer-events-none={step4Locked}
			>
				{@render stepHead(4, false, 'Lock it in')}
				{#if !step4Locked}
					{@const slot = (capturedLast! - capturedFirst!) / Math.max(1, binsInTestSection - 1)}
					{@const w = slot * binsInTestSection}
					<dl class="flex flex-wrap gap-x-6 gap-y-1 text-sm">
						<div class="flex gap-2"><dt class="text-ink-muted">Section width</dt><dd class="num text-ink">{fmt(w, 2)}°</dd></div>
						<div class="flex gap-2"><dt class="text-ink-muted">Offset from home</dt><dd class="num text-ink">{fmt(capturedFirst! - 0.5 * slot, 2)}°</dd></div>
						<div class="flex gap-2"><dt class="text-ink-muted">Pillar</dt><dd class="num text-ink">{fmt(sectionPitchDeg - w, 2)}°</dd></div>
					</dl>
					<Field label="Label" for="aim-label" help="Optional." class="max-w-sm">
						<Input id="aim-label" bind:value={calibrationLabel} placeholder="After moving the home switch" />
					</Field>
				{:else}
					<p class="text-sm text-ink-muted">Capture both bins to work out the geometry and lock it in.</p>
				{/if}
				<div>
					<Button variant="primary" loading={busy} disabled={step4Locked} onclick={deriveAndLockIn}>
						Work it out and lock it in
					</Button>
				</div>
			</li>
		</ol>
	</Panel>

	<Panel title="Saved calibrations" flush>
		{#if calibrations.length === 0}
			<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">
				None yet. Run the calibration above to save one.
			</p>
		{:else}
			<ul class="divide-y divide-line">
				{#each calibrations as cal (cal.id)}
					<li class="flex items-center justify-between gap-3 px-(--pad-panel) py-(--pad-row)">
						<div class="min-w-0 text-sm">
							<div class="flex items-center gap-2">
								<span class="truncate font-medium text-ink">{cal.label ?? 'Calibration'}</span>
								{#if cal.is_active}<Badge tone="success">Active</Badge>{/if}
							</div>
							<div class="num text-ink-muted">
								{fmtDate(cal.created_at)} · N {cal.num_sections} · W {fmt(cal.section_width_deg, 1)}° · θ₀
								{fmt(cal.first_section_offset_deg, 1)}°
							</div>
						</div>
						{#if !cal.is_active}
							<div class="flex shrink-0 items-center gap-2">
								<Button variant="secondary" size="sm" loading={busy} onclick={() => lockIn(cal.id)}>
									Lock in
								</Button>
								<Button variant="ghost" size="sm" onclick={() => deleteCalibration(cal.id)}>Delete</Button>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</Panel>

	<Panel
		title="Reachable bins by layout"
		description="Chute travel 0 to {fmt(maxAngleDeg, 0)}°, with a {fmt(360 - maxAngleDeg, 0)}° no-go wedge at home."
	>
		<div class="flex flex-col gap-4">
			<p class="text-sm text-ink-muted">
				Each layout shows where the chute points for that many bins a section. Bins crossed out in red
				fall in the wedge between the end of travel ({fmt(maxAngleDeg, 0)}°) and home (0°), which is
				what loses bins whenever home does not land on a pillar. Click a reachable bin to test-aim at
				it.
			</p>
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
				{#each VIZ_SIZES as size (size)}
					<BinLayoutViz
						{numSections}
						{sectionWidthDeg}
						{firstSectionOffsetDeg}
						{maxAngleDeg}
						binCount={size}
						liveAngleDeg={currentAngle}
						{selected}
						onSelect={(sel) => (selected = sel)}
					/>
				{/each}
			</div>
			{#if selected}
				<div class="flex flex-wrap items-center gap-3">
					<span class="text-sm text-ink">
						The {selected.binCount}-bin layout, section {selected.section + 1}, bin {selected.bin + 1}:
						<span class="num text-ink-muted">{fmt(angleFor(selected.section, selected.bin, selected.binCount), 2)}°</span>
					</span>
					<Button
						variant="primary"
						loading={busy}
						disabled={!isReachable(angleFor(selected.section, selected.bin, selected.binCount))}
						onclick={testAimSelected}
					>
						Test aim at this bin
					</Button>
				</div>
			{:else}
				<p class="text-sm text-ink-muted">Click a bin in any layout to choose it, then test-aim.</p>
			{/if}
		</div>
	</Panel>
</div>
