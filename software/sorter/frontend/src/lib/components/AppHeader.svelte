<script lang="ts">
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import TopBar from '$lib/components/ui/TopBar.svelte';
	import Wordmark from '$lib/components/ui/Wordmark.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import {
		getBackendHttpBase,
		getBackendWsBase,
		machineHttpBaseUrlFromWsUrl,
		machineWsUrlFromHttpBaseUrl,
		requestBackendRestart,
		waitForBackend
	} from '$lib/backend';
	import SortingProfileDropdown from '$lib/components/SortingProfileDropdown.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { machineDowntime } from '$lib/stores/machineDowntime.svelte';
	import { userConfig } from '$lib/stores/userConfig.svelte';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import House from '@lucide/svelte/icons/house';
	import Pause from '@lucide/svelte/icons/pause';
	import Play from '@lucide/svelte/icons/play';
	import Power from '@lucide/svelte/icons/power';
	import PowerOff from '@lucide/svelte/icons/power-off';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import X from '@lucide/svelte/icons/x';

	const manager = getMachinesContext();

	let dismissedHardwareError = $state<string | null>(null);
	let homingDetailsOpen = $state(false);
	let hardwareAlertOpen = $state(false);
	let restartingBackend = $state(false);
	let restartConfirmOpen = $state(false);
	let powerdownConfirmOpen = $state(false);
	let poweringDown = $state(false);
	let powerdownFailed = $state(false);
	let rebootConfirmOpen = $state(false);
	let rebooting = $state(false);
	let rebootFailed = $state(false);
	let rebootTimedOut = $state(false);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase();
	}

	function currentBackendWsUrl(): string {
		return (
			manager.selectedMachine?.url ??
			machineWsUrlFromHttpBaseUrl(currentBackendBaseUrl()) ??
			`${getBackendWsBase()}/ws`
		);
	}

	function keepSystemStatusFresh(baseUrl: string) {
		const wsUrl = machineWsUrlFromHttpBaseUrl(baseUrl) ?? currentBackendWsUrl();
		manager.ensureConnected(wsUrl);
		manager.queueSystemStatusRefreshes(baseUrl);
	}

	function applySystemActionResponse(
		payload: Record<string, unknown> | null,
		fallbackState: string,
		fallbackStep: string | null
	) {
		const state =
			typeof payload?.hardware_state === 'string' ? payload.hardware_state : fallbackState;
		const step = typeof payload?.message === 'string' ? payload.message : fallbackStep;
		const no_power_development_mode =
			manager.selectedMachine?.systemStatus?.no_power_development_mode ?? false;
		manager.applySystemStatusToSelected({
			hardware_state: state,
			hardware_error: null,
			homing_step: state === 'homing' || state === 'initializing' ? step : null,
			no_power_development_mode
		});
	}

	const liveMachineName = $derived(
		manager.selectedMachine?.identity?.nickname ??
			manager.selectedMachine?.identity?.machine_id.slice(0, 8) ??
			null
	);
	// Show the cached name instantly on load; swap to the live one once the
	// WebSocket identity arrives, and cache it for next time.
	const machineName = $derived(liveMachineName ?? userConfig.machineName);
	$effect(() => {
		if (liveMachineName) userConfig.setMachineName(liveMachineName);
	});
	const machineState = $derived(manager.selectedMachine?.sorterState?.state ?? 'initializing');
	const activeIncidentKind = $derived(
		(
			(manager.selectedMachine?.runtimeStats as Record<string, unknown> | null)
				?.active_incident as Record<string, unknown> | null
		)?.kind ?? null
	);
	const resumeBlockedByFault = $derived(
		activeIncidentKind === 'stepper_stall' || activeIncidentKind === 'chute_needs_homing'
	);
	const hardwareState = $derived(
		manager.selectedMachine?.systemStatus?.hardware_state ?? 'standby'
	);
	const homingStep = $derived(manager.selectedMachine?.systemStatus?.homing_step ?? null);
	const hardwareError = $derived(manager.selectedMachine?.systemStatus?.hardware_error ?? null);

	const cameraHealth = $derived(manager.selectedMachine?.cameraHealth ?? new Map<string, string>());
	const cameraTotal = $derived(cameraHealth.size);
	const cameraActive = $derived(
		Array.from(cameraHealth.values()).filter((status) => status === 'online').length
	);

	const hardwareTone = $derived(
		hardwareState === 'ready'
			? 'success'
			: hardwareState === 'error'
				? 'danger'
				: hardwareState === 'homing' || hardwareState === 'initializing'
					? 'info'
					: 'warning'
	);
	const camerasTone = $derived(
		cameraActive === cameraTotal ? 'success' : cameraActive > 0 ? 'warning' : 'danger'
	);

	const hardwareStateLabel = $derived(
		hardwareState === 'ready'
			? 'Ready'
			: hardwareState === 'standby'
				? 'Standby'
				: hardwareState === 'homing'
					? 'Homing'
					: hardwareState === 'initializing'
						? 'Initializing'
						: hardwareState === 'initialized'
							? 'Initialized'
							: hardwareState === 'error'
								? 'Error'
								: 'Unknown'
	);

	const needsHoming = $derived(
		hardwareState === 'standby' || hardwareState === 'error' || hardwareState === 'initialized'
	);

	async function homeSystem() {
		const baseUrl = currentBackendBaseUrl();
		try {
			const response = await fetch(`${baseUrl}/api/system/recover`, { method: 'POST' });
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			applySystemActionResponse(payload, 'homing', 'Starting safe recovery...');
			keepSystemStatusFresh(baseUrl);
		} catch {
			keepSystemStatusFresh(baseUrl);
		}
	}

	async function initializeSystem() {
		const baseUrl = currentBackendBaseUrl();
		try {
			const response = await fetch(`${baseUrl}/api/system/initialize`, { method: 'POST' });
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			applySystemActionResponse(payload, 'initializing', 'Initializing hardware...');
			keepSystemStatusFresh(baseUrl);
		} catch {
			keepSystemStatusFresh(baseUrl);
		}
	}

	async function togglePauseResume() {
		const resuming = machineState === 'paused' || hardwareState === 'initialized';
		if (resuming && resumeBlockedByFault) return;
		const endpoint = resuming ? '/resume' : '/pause';
		try {
			await fetch(`${currentBackendBaseUrl()}${endpoint}`, { method: 'POST' });
		} catch {
			// ignore
		}
	}

	function requestRestartBackend() {
		restartConfirmOpen = true;
	}

	// Each of these keeps its confirm dialog open and turns it into the
	// dialog that waits (docs/overlays.md), closed when the wait is over.
	async function confirmRestartBackend() {
		restartingBackend = true;
		const baseUrl = currentBackendBaseUrl();
		if (await requestBackendRestart(baseUrl)) {
			await waitForBackend(baseUrl, { maxAttempts: 60 });
			// The new process's identity reopens the camera feeds (see MachineManager).
			manager.connect(currentBackendWsUrl(), { force: true });
		}
		restartingBackend = false;
		restartConfirmOpen = false;
	}

	function requestPowerDown() {
		powerdownConfirmOpen = true;
	}

	async function confirmPowerDown() {
		powerdownFailed = false;
		poweringDown = true;
		machineDowntime.begin();
		const baseUrl = currentBackendBaseUrl();
		try {
			const response = await fetch(`${baseUrl}/api/system/shutdown`, { method: 'POST' });
			if (!response.ok) {
				poweringDown = false;
				powerdownConfirmOpen = false;
				machineDowntime.end();
				powerdownFailed = true;
			}
			// On success, leave the dialog waiting: the machine is going down and
			// the UI will stop responding shortly. There's nothing left to wait for.
		} catch {
			// The request may not return if the OS starts tearing things down before
			// the response is delivered. Treat a dropped connection as success and keep
			// the progress modal up.
		}
	}

	function requestReboot() {
		rebootConfirmOpen = true;
	}

	// The backend answers the reboot request before the OS starts tearing
	// services down, so a probe right after it would still succeed. Wait for the
	// machine to actually go away before we start watching for it to come back.
	async function waitForBackendToGoDown(baseUrl: string): Promise<void> {
		for (let attempt = 0; attempt < 30; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, 1000));
			try {
				await fetch(`${baseUrl}/api/system/status`, {
					signal: AbortSignal.timeout(1500)
				});
			} catch {
				return;
			}
		}
	}

	async function confirmReboot() {
		rebootFailed = false;
		rebootTimedOut = false;
		rebooting = true;
		machineDowntime.begin();
		const baseUrl = currentBackendBaseUrl();
		try {
			const response = await fetch(`${baseUrl}/api/system/reboot`, { method: 'POST' });
			if (!response.ok) {
				rebooting = false;
				rebootConfirmOpen = false;
				machineDowntime.end();
				rebootFailed = true;
				return;
			}
		} catch {
			// The request may not return if the OS starts tearing things down before
			// the response is delivered. Treat a dropped connection as success and
			// wait for the machine to come back.
		}
		await waitForBackendToGoDown(baseUrl);
		// A full boot plus backend startup is a couple of minutes on the Pi.
		const back = await waitForBackend(baseUrl, {
			initialDelayMs: 5000,
			maxAttempts: 180,
			intervalMs: 2000
		});
		rebooting = false;
		rebootConfirmOpen = false;
		machineDowntime.end();
		if (!back) {
			rebootTimedOut = true;
			return;
		}
		manager.connect(currentBackendWsUrl(), { force: true });
	}

	function dismissHardwareBanner() {
		dismissedHardwareError = hardwareError?.message ?? null;
		hardwareAlertOpen = false;
	}

	const showHardwareBanner = $derived(
		Boolean(
			hardwareError &&
				hardwareError.message !== dismissedHardwareError &&
				hardwareState !== 'error'
		)
	);
	const homingHeadline = $derived(homingStep ?? 'Homing all hardware...');
	const blockingHardwareAlert = $derived(
		Boolean(
			hardwareState === 'error' && hardwareError && hardwareError.message !== dismissedHardwareError
		)
	);

	$effect(() => {
		if (!hardwareError) {
			dismissedHardwareError = null;
			hardwareAlertOpen = false;
		}
	});

	$effect(() => {
		if (blockingHardwareAlert) {
			hardwareAlertOpen = true;
		}
	});
	let { sticky = true }: { sticky?: boolean } = $props();

	type SystemItem =
		| 'separator'
		| { label: string; icon: typeof Power; onselect: () => void; danger?: boolean };

	const systemItems = $derived<SystemItem[]>([
		{ label: needsHoming ? 'Home' : 'Re-home', icon: House, onselect: () => void homeSystem() },
		...(hardwareState === 'standby' || hardwareState === 'error'
			? [
					{
						label: 'Initialize without homing',
						icon: Power,
						onselect: () => void initializeSystem()
					}
				]
			: []),
		'separator',
		{ label: 'Restart the backend', icon: RotateCcw, onselect: requestRestartBackend },
		{ label: 'Restart the machine', icon: RotateCw, onselect: requestReboot, danger: true },
		{ label: 'Power down the machine', icon: PowerOff, onselect: requestPowerDown, danger: true }
	]);
</script>

<TopBar
	{sticky}
	collapse="lg"
	items={[
		{ href: '/', label: 'Dashboard' },
		{ href: '/bins', label: 'Bins' },
		{ href: '/3d', label: '3D' },
		{ href: '/profiles', label: 'Profiles' },
		{ href: '/records', label: 'Records' },
		{ href: '/settings', label: 'Settings' }
	]}
>
	{#snippet brand()}<Wordmark />{/snippet}
	{#snippet end()}
		<div class="hidden items-center gap-2 md:flex">
			{#if machineName}
				<span class="text-sm font-medium text-ink" title="Current machine">{machineName}</span>
			{/if}
			<Badge tone={hardwareTone} dot>{hardwareStateLabel}</Badge>
			{#if cameraTotal > 0 && cameraActive < cameraTotal}
				<Badge tone={camerasTone}>{cameraActive}/{cameraTotal} cameras</Badge>
			{/if}
		</div>
		<div class="hidden sm:block"><SortingProfileDropdown /></div>
		{#if hardwareState === 'ready' || hardwareState === 'initialized'}
			{@const resuming = machineState === 'paused' || hardwareState === 'initialized'}
			<Button
				variant="ghost"
				icon={resuming ? Play : Pause}
				label={resuming
					? resumeBlockedByFault
						? activeIncidentKind === 'chute_needs_homing'
							? 'Re-home the chute before resuming'
							: 'Clear the motor stall before resuming'
						: 'Resume'
					: 'Pause'}
				disabled={resuming && resumeBlockedByFault}
				onclick={togglePauseResume}
			/>
		{/if}
		<Menu label="System" items={systemItems}>
			{#snippet trigger(props)}
				<Button {...props} variant="ghost" icon={Ellipsis} label="System menu" />
			{/snippet}
		</Menu>
	{/snippet}
</TopBar>

{#if showHardwareBanner && hardwareError}
	<Alert tone="danger" title={hardwareError.title} class="px-4 sm:px-6">
		<span class="break-words">{hardwareError.message}</span>
		{#snippet actions()}
			{#if needsHoming}
				<Button size="sm" icon={House} onclick={() => void homeSystem()}>Home</Button>
			{/if}
			<Button size="sm" variant="ghost" icon={X} onclick={dismissHardwareBanner}>Dismiss</Button>
		{/snippet}
	</Alert>
{/if}

{#if hardwareState === 'homing'}
	<div
		class="pointer-events-none fixed top-[calc(var(--size-topbar)+0.75rem)] right-4 z-40 w-[min(22rem,calc(100vw-2rem))] sm:right-6"
	>
		<button
			type="button"
			onclick={() => (homingDetailsOpen = true)}
			class="pointer-events-auto flex w-full items-start gap-3 rounded-panel border border-line bg-raised p-3 text-left"
			title="Show the homing details"
		>
			<Spinner size={16} class="mt-0.5 shrink-0 text-info-ink" />
			<span class="min-w-0 flex-1">
				<span class="flex items-baseline justify-between gap-3">
					<span class="text-sm font-medium text-ink">Homing</span>
					<span class="text-sm text-ink-muted">Details</span>
				</span>
				<span class="mt-0.5 block text-sm text-ink-muted">{homingHeadline}</span>
			</span>
		</button>
	</div>
{/if}

<Modal bind:open={hardwareAlertOpen} title={hardwareError?.title ?? 'Machine stopped'} size="sm">
	<p class="break-words">{hardwareError?.message}</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={dismissHardwareBanner}>Close</Button>
		<Button variant="primary" icon={House} onclick={() => void homeSystem()}>Home again</Button>
	{/snippet}
</Modal>

<Modal
	bind:open={restartConfirmOpen}
	title={restartingBackend ? 'Restarting the backend' : 'Restart the backend?'}
	size="sm"
	dismissible={!restartingBackend}
	status={restartingBackend ? 'Waiting for the service to come back' : undefined}
>
	{#if restartingBackend}
		<p class="text-ink-muted">This closes by itself when the backend answers again.</p>
	{:else}
		<p>This restarts the sorter's backend service after releasing the cameras.</p>
		<p class="mt-2 text-ink-muted">
			A running sort or homing stops, the cameras and the hardware start again, and this page is
			unavailable for a few seconds.
		</p>
	{/if}
	{#snippet footer()}
		{#if !restartingBackend}
			<Button variant="ghost" onclick={() => (restartConfirmOpen = false)}>Cancel</Button>
			<Button variant="danger" icon={RotateCcw} onclick={() => void confirmRestartBackend()}>
				Restart the backend
			</Button>
		{/if}
	{/snippet}
</Modal>

<Modal
	bind:open={rebootConfirmOpen}
	title={rebooting ? 'Restarting the machine' : 'Restart the machine?'}
	size="sm"
	dismissible={!rebooting}
	status={rebooting ? 'Waiting for the machine to come back' : undefined}
>
	{#if rebooting}
		<p class="text-ink-muted">
			This page stops answering for a while and reconnects by itself once the machine is back,
			usually in a couple of minutes.
		</p>
	{:else}
		<p>
			This reboots the whole machine, as running <span class="font-mono">reboot</span> on its computer
			would. Everything powers back on by itself.
		</p>
		<p class="mt-2 text-ink-muted">
			A running sort stops, and this page is unavailable for a couple of minutes while the machine
			starts up.
		</p>
	{/if}
	{#snippet footer()}
		{#if !rebooting}
			<Button variant="ghost" onclick={() => (rebootConfirmOpen = false)}>Cancel</Button>
			<Button variant="danger" icon={RotateCw} onclick={() => void confirmReboot()}>
				Restart the machine
			</Button>
		{/if}
	{/snippet}
</Modal>

<Modal bind:open={rebootFailed} title="The restart did not start" size="sm">
	<p>
		The reboot command could not be started, so the machine is still running. The backend's log
		says why.
	</p>
	{#snippet footer()}
		<Button onclick={() => (rebootFailed = false)}>Close</Button>
	{/snippet}
</Modal>

<Modal bind:open={rebootTimedOut} title="The machine is taking a while" size="sm">
	<p>
		The machine rebooted but is not back yet. It may still be starting; reload this page in a minute
		to check again.
	</p>
	{#snippet footer()}
		<Button onclick={() => (rebootTimedOut = false)}>Close</Button>
	{/snippet}
</Modal>

<Modal
	bind:open={powerdownConfirmOpen}
	title={poweringDown ? 'Powering down' : 'Power down the machine?'}
	size="sm"
	dismissible={!poweringDown}
	status={poweringDown ? 'Shutting down' : undefined}
>
	{#if poweringDown}
		<p class="text-ink-muted">
			This page stops answering shortly. Linux can take up to about 2 minutes to power off after
			that; wait until the machine is completely off before cutting its power.
		</p>
	{:else}
		<p>
			This shuts the whole machine down, as running <span class="font-mono">shutdown</span> on its
			computer would. The sorter powers off completely.
		</p>
		<p class="mt-2 text-ink-muted">
			A running sort stops, and turning the machine back on takes someone at the machine.
		</p>
	{/if}
	{#snippet footer()}
		{#if !poweringDown}
			<Button variant="ghost" onclick={() => (powerdownConfirmOpen = false)}>Cancel</Button>
			<Button variant="danger" icon={PowerOff} onclick={() => void confirmPowerDown()}>
				Power down the machine
			</Button>
		{/if}
	{/snippet}
</Modal>

<Modal bind:open={powerdownFailed} title="The power down did not start" size="sm">
	<p>
		The shutdown command could not be started, so the machine is still running. The backend's log
		says why.
	</p>
	{#snippet footer()}
		<Button onclick={() => (powerdownFailed = false)}>Close</Button>
	{/snippet}
</Modal>

<Modal bind:open={homingDetailsOpen} title="Homing" size="sm">
	<div class="flex items-start gap-3">
		<Spinner size={16} class="mt-0.5 text-info-ink" />
		<div>
			<p>{homingHeadline}</p>
			<p class="mt-2 text-ink-muted">
				The machine is starting its hardware and finding each axis's zero. Let it finish before
				starting a run.
			</p>
		</div>
	</div>
	{#snippet footer()}
		<Button onclick={() => (homingDetailsOpen = false)}>Close</Button>
	{/snippet}
</Modal>
