<script lang="ts">
	import { page } from '$app/state';
	import {
		backendHttpBaseUrl,
		backendWsBaseUrl,
		machineHttpBaseUrlFromWsUrl,
		requestBackendRestart,
		waitForBackend
	} from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import SortingProfileDropdown from '$lib/components/SortingProfileDropdown.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { AlertTriangle, ChevronDown, Home, Pause, Play, RefreshCw, RotateCcw, X } from 'lucide-svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	type C234PurgeCounts = {
		c2?: number;
		c3?: number;
		c4_raw?: number;
		c4_dossiers?: number;
	};

	type C234PurgeStatus = {
		active?: boolean;
		phase?: string;
		started_at?: number | null;
		finished_at?: number | null;
		success?: boolean | null;
		reason?: string | null;
		was_paused?: boolean | null;
		cancel_requested?: boolean;
		counts?: C234PurgeCounts;
	};

	let dismissedHardwareError = $state<string | null>(null);
	let homingDetailsOpen = $state(false);
	let hardwareAlertOpen = $state(false);
	let powerMenuOpen = $state(false);
	let restartingBackend = $state(false);
	let restartConfirmOpen = $state(false);
	let purgingC234 = $state(false);
	let cancellingC234Purge = $state(false);
	let c234PurgeModalOpen = $state(false);
	let c234PurgeError = $state<string | null>(null);
	let c234PurgeStatus = $state<C234PurgeStatus>({
		active: false,
		phase: 'idle',
		success: null,
		reason: null,
		counts: { c2: 0, c3: 0, c4_raw: 0, c4_dossiers: 0 }
	});
	let c234PurgePollTimer: ReturnType<typeof setInterval> | null = null;

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	const machineState = $derived(manager.selectedMachine?.sorterState?.state ?? 'initializing');
	const hardwareState = $derived(manager.selectedMachine?.systemStatus?.hardware_state ?? 'standby');
	const homingStep = $derived(manager.selectedMachine?.systemStatus?.homing_step ?? null);
	const hardwareError = $derived(manager.selectedMachine?.systemStatus?.hardware_error ?? null);

	const cameraHealth = $derived(manager.selectedMachine?.cameraHealth ?? new Map<string, string>());
	const cameraTotal = $derived(cameraHealth.size);
	const cameraActive = $derived(
		Array.from(cameraHealth.values()).filter((status) => status === 'online').length
	);

	const powerDotColor = $derived(
		hardwareState === 'ready' ? 'var(--color-success)'
		: hardwareState === 'error' ? 'var(--color-danger)'
		: hardwareState === 'homing' || hardwareState === 'initializing' ? 'var(--color-info)'
		: '#FFD500'
	);

	const hardwareStateLabel = $derived(
		hardwareState === 'ready' ? 'Ready'
		: hardwareState === 'standby' ? 'Standby'
		: hardwareState === 'homing' ? 'Homing'
		: hardwareState === 'initializing' ? 'Initializing'
		: hardwareState === 'initialized' ? 'Initialized'
		: hardwareState === 'error' ? 'Error'
		: 'Unknown'
	);

	const runtimeDotColor = $derived(
		machineState === 'running' ? 'var(--color-success)'
		: machineState === 'paused' ? '#FFD500'
		: machineState === 'initializing' ? 'var(--color-info)'
		: 'var(--color-danger)'
	);

	const runtimeStateLabel = $derived(
		machineState === 'running' ? 'Running'
		: machineState === 'paused' ? 'Paused'
		: machineState === 'initializing' ? 'Starting'
		: 'Unknown'
	);

	const needsHoming = $derived(
		hardwareState === 'standby' || hardwareState === 'error' || hardwareState === 'initialized'
	);
	const c234PurgeCounts = $derived(c234PurgeStatus.counts ?? {});
	const c234PurgeC4Count = $derived(
		Math.max(c234PurgeCounts.c4_raw ?? 0, c234PurgeCounts.c4_dossiers ?? 0)
	);
	const c234PurgeTotal = $derived(
		(c234PurgeCounts.c2 ?? 0)
			+ (c234PurgeCounts.c3 ?? 0)
			+ c234PurgeC4Count
	);
	const c234PurgeActive = $derived(Boolean(c234PurgeStatus.active));
	const c234PurgePhaseLabel = $derived(
		c234PurgeStatus.phase === 'starting' ? 'Starting'
		: c234PurgeStatus.phase === 'purging' ? 'Purging'
		: c234PurgeStatus.phase === 'verifying_clear' ? 'Verifying clear'
		: c234PurgeStatus.phase === 'cancelling' ? 'Cancelling'
		: c234PurgeStatus.phase === 'cancelled' ? 'Cancelled'
		: c234PurgeStatus.success === true ? 'Cleared'
		: c234PurgeStatus.success === false ? 'Stopped'
		: 'Idle'
	);

	async function homeSystem() {
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/home`, { method: 'POST' });
		} catch {
			// ignore
		}
	}

	async function resetHardwareSystem() {
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/reset`, { method: 'POST' });
		} catch {
			// ignore
		}
	}

	async function togglePauseResume() {
		const endpoint = machineState === 'paused' ? '/resume' : '/pause';
		try {
			await fetch(`${currentBackendBaseUrl()}${endpoint}`, { method: 'POST' });
		} catch {
			// ignore
		}
	}

	function requestRestartBackend() {
		powerMenuOpen = false;
		restartConfirmOpen = true;
	}

	async function confirmRestartBackend() {
		restartConfirmOpen = false;
		restartingBackend = true;
		const baseUrl = currentBackendBaseUrl();
		const restart = await requestBackendRestart(baseUrl);
		if (!restart.ok) {
			restartingBackend = false;
			return;
		}
		await waitForBackend(baseUrl, { maxAttempts: 60 });
		restartingBackend = false;
		// Ws will reconnect and push fresh snapshots automatically.
	}

	function stopC234PurgePolling() {
		if (c234PurgePollTimer !== null) {
			clearInterval(c234PurgePollTimer);
			c234PurgePollTimer = null;
		}
	}

	async function refreshC234PurgeStatus() {
		try {
			const response = await fetch(`${currentBackendBaseUrl()}/api/rt/status`, {
				cache: 'no-store'
			});
			if (!response.ok) return;
			const payload = (await response.json()) as {
				maintenance?: { c234_purge?: C234PurgeStatus };
			};
			const status = payload.maintenance?.c234_purge;
			if (!status) return;
			c234PurgeStatus = status;
			if (!status.active) {
				stopC234PurgePolling();
			}
		} catch {
			// keep the modal open; the next poll may succeed after reconnect.
		}
	}

	function startC234PurgePolling() {
		stopC234PurgePolling();
		void refreshC234PurgeStatus();
		c234PurgePollTimer = setInterval(() => {
			void refreshC234PurgeStatus();
		}, 500);
	}

	async function purgeC234() {
		purgingC234 = true;
		c234PurgeModalOpen = true;
		c234PurgeError = null;
		c234PurgeStatus = {
			active: true,
			phase: 'starting',
			success: null,
			reason: null,
			counts: { c2: 0, c3: 0, c4_raw: 0, c4_dossiers: 0 }
		};
		try {
			const response = await fetch(`${currentBackendBaseUrl()}/api/rt/purge/c234`, { method: 'POST' });
			const payload = (await response.json().catch(() => ({}))) as {
				detail?: string;
				status?: C234PurgeStatus;
			};
			if (!response.ok) {
				c234PurgeStatus = { ...c234PurgeStatus, active: false, phase: 'idle', success: false };
				c234PurgeError = payload.detail ?? 'Could not start C2/C3/C4 purge.';
				return;
			}
			if (payload.status) {
				c234PurgeStatus = payload.status;
			}
			startC234PurgePolling();
		} catch {
			c234PurgeStatus = { ...c234PurgeStatus, active: false, phase: 'idle', success: false };
			c234PurgeError = 'Could not reach the backend to start C2/C3/C4 purge.';
		} finally {
			purgingC234 = false;
			powerMenuOpen = false;
		}
	}

	async function cancelC234Purge() {
		cancellingC234Purge = true;
		c234PurgeError = null;
		try {
			const response = await fetch(`${currentBackendBaseUrl()}/api/rt/purge/c234/cancel`, {
				method: 'POST'
			});
			const payload = (await response.json().catch(() => ({}))) as {
				detail?: string;
				status?: C234PurgeStatus;
			};
			if (!response.ok) {
				c234PurgeError = payload.detail ?? 'Could not cancel C2/C3/C4 purge.';
				return;
			}
			if (payload.status) {
				c234PurgeStatus = payload.status;
			}
			startC234PurgePolling();
		} catch {
			c234PurgeError = 'Could not reach the backend to cancel C2/C3/C4 purge.';
		} finally {
			cancellingC234Purge = false;
		}
	}

	function handlePowerMenuClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('[data-power-menu]')) {
			powerMenuOpen = false;
		}
	}

	async function retryHardwareAction() {
		if (isControlBoardConnectionError(hardwareError)) {
			await homeSystem();
			return;
		}
		if (isFeederTransportBlocked(hardwareError)) {
			// Nothing to refetch — WS pushes new status automatically.
			return;
		}
		if (hardwareState === 'standby' || hardwareState === 'error') {
			await homeSystem();
			return;
		}
	}

	function dismissHardwareBanner() {
		dismissedHardwareError = hardwareError;
		hardwareAlertOpen = false;
	}

	function isFeederTransportBlocked(message: string | null): boolean {
		return Boolean(
			message &&
				(message.startsWith('Feeder transport blocked') ||
					message.startsWith('Feeder stalled before C-Channel 2'))
		);
	}

	function isFeederDetectionUnavailable(message: string | null): boolean {
		return Boolean(message && message.startsWith('Feeder camera detection unavailable'));
	}

	function isControlBoardConnectionError(message: string | null): boolean {
		return Boolean(message && message.startsWith('No SorterInterface devices found on buses'));
	}

	function isChuteJam(message: string | null): boolean {
		return Boolean(message && message.startsWith('Chute jam'));
	}

	function hardwareAlertBody(message: string | null): string {
		if (!message) return '';
		if (isFeederTransportBlocked(message)) {
			const separator = message.indexOf(': ');
			return separator >= 0 ? message.slice(separator + 2) : message;
		}
		if (isFeederDetectionUnavailable(message)) {
			return 'The feeder cameras are currently not delivering reliable live data. Please check the C-Channel camera connections and make sure the live feeds are updating.';
		}
		if (isControlBoardConnectionError(message)) {
			return 'The machine could not connect to its control boards. Please check that the control boards are powered and the USB cables are connected properly.';
		}
		const separator = message.indexOf(': ');
		return separator >= 0 ? message.slice(separator + 2) : message;
	}

	function hardwareAlertHelp(message: string | null): string | null {
		if (!message) return null;
		if (isFeederTransportBlocked(message)) {
			return 'After checking the feeder, close this dialog and press play to continue.';
		}
		if (isFeederDetectionUnavailable(message)) {
			return 'After fixing the camera connection, reset the hardware runtime and home the machine again.';
		}
		if (isControlBoardConnectionError(message)) {
			return 'If everything is connected, reset the hardware runtime and try homing again.';
		}
		return null;
	}

	const showHardwareBanner = $derived(
		Boolean(hardwareError && hardwareError !== dismissedHardwareError && hardwareState !== 'error')
	);
	const hardwareBannerActionLabel = $derived(
		isFeederDetectionUnavailable(hardwareError)
			? 'Reset Hardware'
			: isFeederTransportBlocked(hardwareError)
			? 'Refresh Status'
			: hardwareState === 'standby' || hardwareState === 'error'
				? 'Retry Home'
				: 'Refresh Status'
	);
	const homingHeadline = $derived(homingStep ?? 'Homing all hardware...');
	const hardwareAlertTitle = $derived(
		isFeederTransportBlocked(hardwareError)
			? 'Feeder Check Required'
			: isFeederDetectionUnavailable(hardwareError)
				? 'Feeder Cameras Not Ready'
			: isControlBoardConnectionError(hardwareError)
				? 'Control Boards Not Reachable'
			: isChuteJam(hardwareError)
				? 'Chute Jammed'
				: 'Machine Alert'
	);
	const blockingHardwareAlert = $derived(
		Boolean(hardwareState === 'error' && hardwareError && hardwareError !== dismissedHardwareError)
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

	onMount(() => {
		if (manager.machines.size === 0) {
			manager.connect(`${backendWsBaseUrl}/ws`);
		}
		document.addEventListener('click', handlePowerMenuClickOutside);
		return () => {
			document.removeEventListener('click', handlePowerMenuClickOutside);
			stopC234PurgePolling();
		};
	});
</script>

<nav class="border-b border-border bg-surface">
	<div class="flex items-center justify-between px-4 py-3 sm:px-6">
		<div class="flex items-center gap-6">
			<a href="/" class="flex items-center gap-2.5 text-xl font-bold font-mono uppercase tracking-tight text-text">
				<span class="h-5 w-5 shrink-0 bg-primary" aria-hidden="true"></span>
				Sorter
			</a>
			<div class="flex gap-1">
				<a
					href="/"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname === '/' ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Dashboard
				</a>
				<a
					href="/bins"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname === '/bins' ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Bins
				</a>
				<a
					href="/profiles"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname === '/profiles' ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Profiles
				</a>
				<a
					href="/tracked"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname.startsWith('/tracked') ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Tracked
				</a>
				<a
					href="/logs"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname.startsWith('/logs') ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Logs
				</a>
				<a
					href="/settings"
					class="px-3 py-1.5 text-sm font-medium transition-colors {page.url.pathname.startsWith('/settings') ? 'border-b-2 border-primary text-primary' : 'text-text-muted hover:text-text hover:bg-bg'}"
				>
					Settings
				</a>
			</div>
		</div>
		<div class="flex items-center gap-2">
			<SortingProfileDropdown />

			{#if hardwareState === 'ready'}
				<button
					onclick={togglePauseResume}
					class="p-2 text-text transition-colors hover:bg-bg"
					title={machineState === 'paused' ? 'Resume' : 'Pause'}
				>
					{#if machineState === 'paused'}
						<Play size={20} />
					{:else}
						<Pause size={20} />
					{/if}
				</button>
			{/if}

			<div class="relative" data-power-menu>
				<button
					onclick={() => (powerMenuOpen = !powerMenuOpen)}
					class="flex items-center gap-1.5 p-2 text-text-muted transition-colors hover:text-text hover:bg-bg"
					title="System controls"
				>
					<span
						class="inline-block h-4 w-4 shrink-0"
						style="background-color: {powerDotColor}; border-radius: 50%;"
					></span>
					<ChevronDown size={12} class={`transition-transform duration-150 ${powerMenuOpen ? 'rotate-180' : ''}`} />
				</button>

				{#if powerMenuOpen}
					<div class="absolute right-0 top-full z-50 mt-1 w-[260px] border border-border bg-surface shadow-lg">
						<div class="px-3 pt-2.5 pb-1.5 text-xs font-semibold uppercase tracking-wider text-text-muted">
							System Status
						</div>
						<div class="flex flex-col gap-0.5 px-3 pb-2.5">
							<div class="flex items-center justify-between py-1">
								<span class="text-xs text-text-muted">Hardware</span>
								<span class="flex items-center gap-1.5 text-xs font-medium text-text">
									<span class="inline-block h-1.5 w-1.5" style="background-color: {powerDotColor}; border-radius: 50%;"></span>
									{hardwareStateLabel}
								</span>
							</div>
							<div class="flex items-center justify-between py-1">
								<span class="text-xs text-text-muted">Runtime</span>
								<span class="flex items-center gap-1.5 text-xs font-medium text-text">
									<span class="inline-block h-1.5 w-1.5" style="background-color: {runtimeDotColor}; border-radius: 50%;"></span>
									{runtimeStateLabel}
								</span>
							</div>
							{#if cameraTotal > 0}
								<div class="flex items-center justify-between py-1">
									<span class="text-xs text-text-muted">Cameras</span>
									<span class="flex items-center gap-1.5 text-xs font-medium text-text">
										<span
											class="inline-block h-1.5 w-1.5"
											style="background-color: {cameraActive === cameraTotal ? 'var(--color-success)' : cameraActive > 0 ? '#FFD500' : 'var(--color-danger)'}; border-radius: 50%;"
										></span>
										{cameraActive}/{cameraTotal} active
									</span>
								</div>
							{/if}
						</div>
						<div class="border-t border-border">
							<div class="px-3 pt-2 pb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
								Actions
							</div>
							<button
								onclick={() => { homeSystem(); powerMenuOpen = false; }}
								class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg"
							>
								<Home size={14} class="text-text-muted" />
								{#if needsHoming}
									Home
								{:else}
									Re-Home
								{/if}
							</button>
							<button
								onclick={() => { resetHardwareSystem(); powerMenuOpen = false; }}
								class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg"
							>
								<RefreshCw size={14} class="text-text-muted" />
								Reset Hardware
							</button>
							<button
								onclick={() => void purgeC234()}
								disabled={purgingC234 || hardwareState !== 'ready'}
								title={hardwareState === 'ready' ? 'Purge all C2/C3/C4 trays' : 'Home the hardware before purging C2/C3/C4'}
								class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg disabled:cursor-wait disabled:opacity-60"
							>
								<RefreshCw size={14} class={`text-text-muted ${purgingC234 ? 'animate-spin' : ''}`} />
								Purge C2/C3/C4
							</button>
							<button
								onclick={requestRestartBackend}
								class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg"
							>
								<RotateCcw size={14} class="text-text-muted" />
								Hard Restart Backend
							</button>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>

	{#if hardwareState === 'homing'}
		<div class="pointer-events-none fixed top-[4.7rem] right-4 z-40 w-[min(360px,calc(100vw-2rem))] sm:right-6">
			<button
				type="button"
				onclick={() => (homingDetailsOpen = true)}
				class="pointer-events-auto flex w-full items-start gap-3 border border-border bg-surface px-3 py-3 text-left shadow-[0_12px_28px_rgba(15,23,42,0.12)] transition-colors hover:bg-surface hover:border-[#C9C7C0]"
				title="Show hardware homing details"
			>
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-info/[0.08] text-info">
					<div class="h-4 w-4 animate-spin border-2 border-current border-t-transparent" style="border-radius: 50%;"></div>
				</div>
				<div class="min-w-0 flex-1">
					<div class="flex items-center justify-between gap-3">
						<div class="text-xs font-semibold uppercase tracking-wider text-info">Hardware Homing</div>
						<div class="text-xs text-text-muted">View details</div>
					</div>
					<div class="mt-1 text-sm text-text">{homingHeadline}</div>
					<div class="mt-2 text-sm text-text-muted">The machine is currently initializing and referencing its hardware.</div>
				</div>
			</button>
		</div>
	{/if}

	{#if showHardwareBanner}
		<div class="border-t border-danger/30 bg-danger/[0.06] px-4 py-3 sm:px-6">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div class="flex min-w-0 gap-3">
					<div class="flex h-8 w-8 shrink-0 items-center justify-center border border-danger/30 bg-danger/10 text-[#B11618]">
						<AlertTriangle size={16} />
					</div>
					<div class="min-w-0">
						<div class="text-xs font-semibold uppercase tracking-wider text-[#B11618]">
							Machine Alert
						</div>
						<div class="mt-1 text-sm text-text">{hardwareAlertBody(hardwareError)}</div>
					</div>
				</div>

				<div class="flex items-center gap-2 sm:shrink-0">
					<button
						type="button"
						onclick={() => void retryHardwareAction()}
						class="inline-flex items-center gap-1.5 border border-danger/30 bg-white/75 px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-white"
					>
						{#if hardwareState === 'standby' || hardwareState === 'error'}
							<Home size={14} />
						{:else}
							<RefreshCw size={14} />
						{/if}
						{hardwareBannerActionLabel}
					</button>
					<button
						type="button"
						onclick={dismissHardwareBanner}
						class="inline-flex items-center gap-1.5 border border-border bg-transparent px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-white/60 hover:text-text"
					>
						<X size={14} />
						Dismiss
					</button>
				</div>
			</div>
		</div>
	{/if}

	<Modal bind:open={hardwareAlertOpen} title={hardwareAlertTitle}>
		<div class="flex flex-col gap-4">
			<div class="flex items-start gap-3">
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-danger/25 bg-danger/[0.08] text-[#B11618]">
					<AlertTriangle size={18} />
				</div>
				<div>
					<div class="text-sm text-text">{hardwareAlertBody(hardwareError)}</div>
					{#if hardwareAlertHelp(hardwareError)}
						<div class="mt-2 text-sm text-text-muted">
							{hardwareAlertHelp(hardwareError)}
						</div>
					{/if}
					{#if hardwareError && ((isControlBoardConnectionError(hardwareError) || isFeederDetectionUnavailable(hardwareError)) || (!isFeederTransportBlocked(hardwareError) && hardwareAlertBody(hardwareError) !== hardwareError))}
						<details class="mt-3 border border-border bg-bg px-3 py-2 text-xs text-text-muted">
							<summary class="cursor-pointer select-none font-medium text-text">Technical details</summary>
							<div class="mt-2 break-words">{hardwareError}</div>
						</details>
					{/if}
				</div>
			</div>

			<div class="flex items-center justify-end gap-2 border-t border-border pt-3">
				{#if isControlBoardConnectionError(hardwareError) || isFeederDetectionUnavailable(hardwareError)}
					<button
						type="button"
						onclick={() => void resetHardwareSystem()}
						class="inline-flex items-center gap-1.5 border border-danger/25 bg-white px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-bg"
					>
						<RefreshCw size={14} />
						Reset Hardware
					</button>
				{/if}
				<button
					type="button"
					onclick={() => void retryHardwareAction()}
					class="inline-flex items-center gap-1.5 border border-danger/25 bg-white px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-bg"
				>
					{#if hardwareBannerActionLabel === 'Retry Home'}
						<Home size={14} />
					{:else}
						<RefreshCw size={14} />
					{/if}
					{hardwareBannerActionLabel}
				</button>
				<button
					type="button"
					onclick={dismissHardwareBanner}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-surface"
				>
					<X size={14} />
					Close
				</button>
			</div>
		</div>
	</Modal>

	<Modal bind:open={restartConfirmOpen} title="Hard Restart Backend?">
		<div class="flex flex-col gap-4">
			<div class="flex items-start gap-3">
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-danger/25 bg-danger/[0.08] text-[#B11618]">
					<AlertTriangle size={18} />
				</div>
				<div>
					<div class="text-sm text-text">
						This will forcibly restart the sorter backend service.
					</div>
					<div class="mt-2 text-sm text-text-muted">
						Any running sort or homing operation will be interrupted. Cameras and hardware
						state will be re-initialized. The UI will be unavailable for a few seconds.
					</div>
				</div>
			</div>

			<div class="flex items-center justify-end gap-2 border-t border-border pt-3">
				<button
					type="button"
					onclick={() => (restartConfirmOpen = false)}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-surface"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={() => void confirmRestartBackend()}
					class="inline-flex items-center gap-1.5 border border-danger/25 bg-danger/[0.08] px-3 py-1.5 text-sm font-medium text-[#B11618] transition-colors hover:bg-danger/[0.14]"
				>
					<RotateCcw size={14} />
					Restart Backend
				</button>
			</div>
		</div>
	</Modal>

	<Modal bind:open={c234PurgeModalOpen} title="Purge C2/C3/C4">
		<div class="flex flex-col gap-4">
			<div class="flex items-start gap-3">
				<div class="flex h-10 w-10 shrink-0 items-center justify-center border border-border bg-primary/[0.08] text-primary">
					{#if c234PurgeActive}
						<div class="h-5 w-5 animate-spin border-2 border-current border-t-transparent" style="border-radius: 50%;"></div>
					{:else}
						<RefreshCw size={18} />
					{/if}
				</div>
				<div class="min-w-0 flex-1">
					<div class="flex items-center justify-between gap-3">
						<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">
							{c234PurgePhaseLabel}
						</div>
						<div class="font-mono text-xs text-text-muted">
							{c234PurgeTotal} detected
						</div>
					</div>
					<div class="mt-1 text-sm text-text">
						{#if c234PurgeActive}
							Runtime is clearing the C2, C3 and C4 trays. C1 / bulk feeding stays untouched.
						{:else if c234PurgeStatus.success === true}
							C2, C3 and C4 reported clear.
						{:else if c234PurgeStatus.reason === 'cancelled'}
							Purge was cancelled. No further purge moves will be requested.
						{:else if c234PurgeStatus.success === false}
							Purge stopped before all trays reported clear.
						{:else}
							Ready to purge the C-channel trays.
						{/if}
					</div>
					{#if c234PurgeError}
						<div class="mt-3 border border-danger/25 bg-danger/[0.06] px-3 py-2 text-sm text-[#B11618]">
							{c234PurgeError}
						</div>
					{/if}
				</div>
			</div>

			<div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
				<div class="border border-border bg-surface px-3 py-2">
					<div class="text-[0.65rem] font-semibold uppercase tracking-wider text-text-muted">C2</div>
					<div class="mt-1 font-mono text-lg font-semibold text-text">{c234PurgeCounts.c2 ?? 0}</div>
				</div>
				<div class="border border-border bg-surface px-3 py-2">
					<div class="text-[0.65rem] font-semibold uppercase tracking-wider text-text-muted">C3</div>
					<div class="mt-1 font-mono text-lg font-semibold text-text">{c234PurgeCounts.c3 ?? 0}</div>
				</div>
				<div class="border border-border bg-surface px-3 py-2">
					<div class="text-[0.65rem] font-semibold uppercase tracking-wider text-text-muted">C4 visible</div>
					<div class="mt-1 font-mono text-lg font-semibold text-text">{c234PurgeCounts.c4_raw ?? 0}</div>
				</div>
				<div class="border border-border bg-surface px-3 py-2">
					<div class="text-[0.65rem] font-semibold uppercase tracking-wider text-text-muted">C4 owned</div>
					<div class="mt-1 font-mono text-lg font-semibold text-text">{c234PurgeCounts.c4_dossiers ?? 0}</div>
				</div>
			</div>

			<div class="border border-border bg-bg px-3 py-2 text-xs text-text-muted">
				Phase: <span class="font-mono text-text">{c234PurgeStatus.phase ?? 'idle'}</span>
				{#if c234PurgeStatus.reason}
					<span class="mx-2 text-border">|</span>
					Reason: <span class="font-mono text-text">{c234PurgeStatus.reason}</span>
				{/if}
			</div>

			<div class="flex items-center justify-end gap-2 border-t border-border pt-3">
				{#if c234PurgeActive}
					<button
						type="button"
						onclick={() => void cancelC234Purge()}
						disabled={cancellingC234Purge || c234PurgeStatus.cancel_requested}
						class="inline-flex items-center gap-1.5 border border-danger/25 bg-danger/[0.08] px-3 py-1.5 text-sm font-medium text-[#B11618] transition-colors hover:bg-danger/[0.14] disabled:cursor-wait disabled:opacity-60"
					>
						<X size={14} />
						{cancellingC234Purge || c234PurgeStatus.cancel_requested ? 'Cancelling...' : 'Cancel Purge'}
					</button>
				{:else}
					<button
						type="button"
						onclick={() => (c234PurgeModalOpen = false)}
						class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-surface"
					>
						Close
					</button>
				{/if}
			</div>
		</div>
	</Modal>

	{#if restartingBackend}
		<div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
			<div class="flex flex-col items-center gap-4 border border-border bg-surface px-10 py-8 shadow-lg">
				<div class="h-6 w-6 animate-spin border-2 border-primary border-t-transparent" style="border-radius: 50%;"></div>
				<div class="text-sm font-medium text-text">Restarting backend...</div>
				<div class="text-xs text-text-muted">Waiting for the service to come back online.</div>
			</div>
		</div>
	{/if}

	<Modal bind:open={homingDetailsOpen} title="Hardware Homing">
		<div class="flex flex-col gap-4">
			<div class="flex items-start gap-3">
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-info/[0.08] text-info">
					<div class="h-4 w-4 animate-spin border-2 border-current border-t-transparent" style="border-radius: 50%;"></div>
				</div>
				<div>
					<div class="text-xs font-semibold uppercase tracking-wider text-info">Current step</div>
					<div class="mt-1 text-sm text-text">{homingHeadline}</div>
					<div class="mt-2 text-sm text-text-muted">
						The machine is currently initializing and referencing its hardware. Let the process finish before starting a run.
					</div>
				</div>
			</div>

			<div class="flex items-center justify-end gap-2 border-t border-border pt-3">
				<button
					type="button"
					onclick={() => (homingDetailsOpen = false)}
					class="inline-flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm text-text transition-colors hover:bg-surface"
				>
					Close
				</button>
			</div>
		</div>
	</Modal>
</nav>
