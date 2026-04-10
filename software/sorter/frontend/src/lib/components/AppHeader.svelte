<script lang="ts">
	import { page } from '$app/state';
	import { backendHttpBaseUrl, backendWsBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import SortingProfileDropdown from '$lib/components/SortingProfileDropdown.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { AlertTriangle, ChevronDown, Home, Pause, Play, Power, RefreshCw, RotateCcw, X } from 'lucide-svelte';
	import { onMount } from 'svelte';

	const manager = getMachinesContext();

	let machineState = $state('initializing');
	let hardwareState = $state<string>('standby');
	let homingStep = $state<string | null>(null);
	let hardwareError = $state<string | null>(null);
	let dismissedHardwareError = $state<string | null>(null);
	let homingDetailsOpen = $state(false);
	let hardwareAlertOpen = $state(false);
	let powerMenuOpen = $state(false);
	let restartingBackend = $state(false);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	async function fetchState() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/state`);
			if (!res.ok) return;
			const data = await res.json();
			machineState = data.state ?? 'initializing';
		} catch {
			// ignore
		}
	}

	async function fetchSystemStatus() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/status`);
			if (!res.ok) return;
			const data = await res.json();
			hardwareState = data.hardware_state ?? 'standby';
			homingStep = data.homing_step ?? null;
			hardwareError = data.hardware_error ?? null;
		} catch {
			// ignore
		}
	}

	async function homeSystem() {
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/home`, { method: 'POST' });
			await fetchSystemStatus();
		} catch {
			// ignore
		}
	}

	async function resetHardwareSystem() {
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/reset`, { method: 'POST' });
			await fetchSystemStatus();
			await fetchState();
		} catch {
			// ignore
		}
	}

	async function togglePauseResume() {
		const endpoint = machineState === 'paused' ? '/resume' : '/pause';
		try {
			await fetch(`${currentBackendBaseUrl()}${endpoint}`, { method: 'POST' });
			await fetchState();
		} catch {
			// ignore
		}
	}

	async function restartBackend() {
		powerMenuOpen = false;
		restartingBackend = true;
		try {
			await fetch(`${currentBackendBaseUrl()}/api/system/restart`, { method: 'POST' });
		} catch {
			// Expected — connection drops during restart
		}
		// Poll until backend is back
		await waitForBackend();
		restartingBackend = false;
		void fetchState();
		void fetchSystemStatus();
	}

	async function waitForBackend() {
		// Give it a moment to actually go down
		await new Promise((r) => setTimeout(r, 1500));
		const maxAttempts = 60;
		for (let i = 0; i < maxAttempts; i++) {
			try {
				const res = await fetch(`${currentBackendBaseUrl()}/api/system/status`, {
					signal: AbortSignal.timeout(2000)
				});
				if (res.ok) return;
			} catch {
				// Still down
			}
			await new Promise((r) => setTimeout(r, 500));
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
			await fetchSystemStatus();
			return;
		}
		if (hardwareState === 'standby' || hardwareState === 'error') {
			await homeSystem();
			return;
		}
		await fetchSystemStatus();
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
		void fetchState();
		void fetchSystemStatus();
		const interval = setInterval(() => {
			void fetchState();
			void fetchSystemStatus();
		}, 1000);
		document.addEventListener('click', handlePowerMenuClickOutside);
		return () => {
			clearInterval(interval);
			document.removeEventListener('click', handlePowerMenuClickOutside);
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
			<MachineDropdown />

			{#if hardwareState === 'standby' || hardwareState === 'error' || hardwareState === 'initialized'}
				<button
					onclick={homeSystem}
					class="flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-surface"
					title={hardwareState === 'initialized'
						? 'Home all axes'
						: 'Initialize hardware and home all axes'}
				>
					<Home size={14} />
					Home
				</button>
			{:else if hardwareState === 'ready'}
				<button
					onclick={homeSystem}
					class="flex items-center gap-1.5 border border-border bg-bg px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-surface"
					title="Re-home all axes"
				>
					<Home size={14} />
					Re-Home
				</button>
			{/if}

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
					class="flex items-center gap-1 p-2 text-text-muted transition-colors hover:text-text hover:bg-bg"
					title="System controls"
				>
					<Power size={16} />
					<ChevronDown size={12} class={`transition-transform duration-150 ${powerMenuOpen ? 'rotate-180' : ''}`} />
				</button>

				{#if powerMenuOpen}
					<div class="absolute right-0 top-full z-50 mt-1 min-w-[180px] border border-border bg-surface shadow-lg">
						<div class="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
							Service Control
						</div>
						<button
							onclick={restartBackend}
							class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg"
						>
							<RotateCcw size={14} class="text-text-muted" />
							Restart Backend
						</button>
						<button
							onclick={() => { resetHardwareSystem(); powerMenuOpen = false; }}
							class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-text transition-colors hover:bg-bg"
						>
							<RefreshCw size={14} class="text-text-muted" />
							Reset Hardware
						</button>
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
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-[#0055BF]/[0.08] text-[#0055BF]">
					<div class="h-4 w-4 animate-spin border-2 border-current border-t-transparent" style="border-radius: 50%;"></div>
				</div>
				<div class="min-w-0 flex-1">
					<div class="flex items-center justify-between gap-3">
						<div class="text-[11px] font-semibold uppercase tracking-wider text-[#0055BF]">Hardware Homing</div>
						<div class="text-[11px] text-text-muted">View details</div>
					</div>
					<div class="mt-1 text-sm text-text">{homingHeadline}</div>
					<div class="mt-2 text-xs text-text-muted">The machine is currently initializing and referencing its hardware.</div>
				</div>
			</button>
		</div>
	{/if}

	{#if showHardwareBanner}
		<div class="border-t border-[#D01012]/30 bg-[#D01012]/[0.06] px-4 py-3 sm:px-6">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div class="flex min-w-0 gap-3">
					<div class="flex h-8 w-8 shrink-0 items-center justify-center border border-[#D01012]/30 bg-[#D01012]/10 text-[#B11618]">
						<AlertTriangle size={16} />
					</div>
					<div class="min-w-0">
						<div class="text-[11px] font-semibold uppercase tracking-wider text-[#B11618]">Machine Alert</div>
						<div class="mt-1 text-sm text-text">{hardwareAlertBody(hardwareError)}</div>
					</div>
				</div>

				<div class="flex items-center gap-2 sm:shrink-0">
					<button
						type="button"
						onclick={() => void retryHardwareAction()}
						class="inline-flex items-center gap-1.5 border border-[#D01012]/30 bg-white/75 px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-white"
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
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-[#D01012]/25 bg-[#D01012]/[0.08] text-[#B11618]">
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
						class="inline-flex items-center gap-1.5 border border-[#D01012]/25 bg-white px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-bg"
					>
						<RefreshCw size={14} />
						Reset Hardware
					</button>
				{/if}
				<button
					type="button"
					onclick={() => void retryHardwareAction()}
					class="inline-flex items-center gap-1.5 border border-[#D01012]/25 bg-white px-3 py-1.5 text-sm font-medium text-text transition-colors hover:bg-bg"
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
				<div class="flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-[#0055BF]/[0.08] text-[#0055BF]">
					<div class="h-4 w-4 animate-spin border-2 border-current border-t-transparent" style="border-radius: 50%;"></div>
				</div>
				<div>
					<div class="text-[11px] font-semibold uppercase tracking-wider text-[#0055BF]">Current step</div>
					<div class="mt-1 text-sm text-text">{homingHeadline}</div>
					<div class="mt-2 text-sm text-text-muted">
						The machine is currently initializing and referencing its hardware. Let the process finish before starting a run.
					</div>
				</div>
			</div>

			<div class="flex items-center justify-end gap-2 border-t border-border pt-3">
				<button
					type="button"
					onclick={() => void fetchSystemStatus()}
					class="inline-flex items-center gap-1.5 border border-border bg-surface px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg"
				>
					<RefreshCw size={14} />
					Refresh Status
				</button>
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
