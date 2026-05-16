<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext, getMachinesContext } from '$lib/machines/context';
	import {
		backendHttpBaseUrl,
		backendWsBaseUrl,
		machineHttpBaseUrlFromWsUrl,
		machineWsUrlFromHttpBaseUrl
	} from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import CollapsibleSection from '$lib/components/CollapsibleSection.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import ResizeHandle from '$lib/components/ResizeHandle.svelte';
	import SampleCollectionSpeedPanel from '$lib/components/SampleCollectionSpeedPanel.svelte';
	import SidebarBottomTabs from '$lib/components/SidebarBottomTabs.svelte';
	import SortingStatusCard from '$lib/components/SortingStatusCard.svelte';
	import { buildDashboardFeedCrops, type DashboardFeedCrop } from '$lib/dashboard/crops';
	import { Eye, EyeOff } from 'lucide-svelte';

	const SIDEBAR_MIN = 300;
	const SIDEBAR_MAX = 900;
	const SIDEBAR_DEFAULT = 420;

	const machine = getMachineContext();
	const manager = getMachinesContext();

	let dashboardCrops = $state<Record<string, DashboardFeedCrop | null>>({});
	let cropBaseUrl = $state<string | null>(null);
	let sidebar_width = $state(SIDEBAR_DEFAULT);
	let startSystemError = $state<string | null>(null);
	let startSystemPending = $state(false);
	let classification_view = $state<'top' | 'bottom'>('top');
	let classification_layer = $state<'raw' | 'annotated'>('annotated');
	let machineSetup = $state<'standard_carousel' | 'classification_channel' | 'manual_carousel'>(
		'standard_carousel'
	);
	let showSampleCapture = $state(false);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	function onSidebarResize(delta: number) {
		sidebar_width = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, sidebar_width - delta));
	}

	const camera_layout = $derived(machine.machine?.sorterState?.camera_layout ?? 'default');
	const cameraConfig = $derived<Record<string, number | string | null>>(
		machine.machine?.camerasConfig?.cameras ?? {}
	);
	const c4CameraRole = $derived(
		machineSetup === 'classification_channel' || isConfigured('classification_channel')
			? 'classification_channel'
			: 'carousel'
	);
	const hardwareState = $derived(machine.machine?.systemStatus?.hardware_state ?? 'standby');
	const hardwareError = $derived(
		startSystemError ?? machine.machine?.systemStatus?.hardware_error ?? null
	);
	const homingStep = $derived(machine.machine?.systemStatus?.homing_step ?? null);
	const startingSystem = $derived(hardwareState === 'homing' || startSystemPending);

	async function startSystem() {
		const baseUrl = currentBackendBaseUrl();
		startSystemError = null;
		startSystemPending = true;
		try {
			const response = await fetch(`${baseUrl}/api/system/recover`, { method: 'POST' });
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			if (!response.ok || payload?.ok === false) {
				throw new Error(
					typeof payload?.message === 'string' ? payload.message : 'Failed to recover system'
				);
			}
			manager.applySystemStatusToSelected({
				hardware_state:
					typeof payload?.hardware_state === 'string' ? payload.hardware_state : 'homing',
				hardware_error: null,
				homing_step:
					typeof payload?.message === 'string' ? payload.message : 'Starting safe recovery...'
			});
			const wsUrl = machineWsUrlFromHttpBaseUrl(baseUrl) ?? `${backendWsBaseUrl}/ws`;
			manager.ensureConnected(wsUrl);
			manager.queueSystemStatusRefreshes(baseUrl);
		} catch (e: any) {
			startSystemError = e?.message ?? 'Failed to recover system';
			manager.queueSystemStatusRefreshes(baseUrl);
		} finally {
			startSystemPending = false;
		}
	}

	function isConfigured(role: string): boolean {
		const value = cameraConfig[role];
		if (typeof value === 'number') return Number.isFinite(value) && value >= 0;
		if (typeof value === 'string') {
			const normalized = value.trim().toLowerCase();
			return normalized.length > 0 && !['none', 'null', '-1'].includes(normalized);
		}
		return false;
	}

	function cropFor(role: string): DashboardFeedCrop | null {
		if (role === 'carousel' && machineSetup === 'classification_channel') {
			return dashboardCrops.classification_channel ?? dashboardCrops.carousel ?? null;
		}
		return dashboardCrops[role] ?? null;
	}

	function preferredClassificationCamera(hasTop: boolean, hasBottom: boolean): 'classification_top' | 'classification_bottom' | null {
		if (classification_view === 'bottom' && hasBottom) return 'classification_bottom';
		if (hasTop) return 'classification_top';
		if (hasBottom) return 'classification_bottom';
		return null;
	}

	function classificationTabClass(active: boolean): string {
		return active
			? 'border-primary text-text'
			: 'border-transparent text-text-muted hover:text-text';
	}

	async function fetchDashboardCrops(baseUrl: string) {
		try {
			const res = await fetch(`${baseUrl}/api/polygons`);
			if (!res.ok) {
				dashboardCrops = {};
				return;
			}
			dashboardCrops = buildDashboardFeedCrops(await res.json());
		} catch {
			dashboardCrops = {};
		}
	}

	async function loadMachineSetup(baseUrl: string) {
		try {
			const res = await fetch(`${baseUrl}/api/machine-setup`);
			if (!res.ok) return;
			const payload = await res.json();
			if (
				payload?.setup === 'classification_channel' ||
				payload?.setup === 'manual_carousel' ||
				payload?.setup === 'standard_carousel'
			) {
				machineSetup = payload.setup;
			}
		} catch {
			// ignore transient shell fetch issues
		}
	}

	async function loadDashboardConfig(baseUrl: string) {
		try {
			const res = await fetch(`${baseUrl}/api/system/dashboard-config`);
			if (!res.ok) return;
			const payload = await res.json();
			showSampleCapture = Boolean(payload?.show_sample_capture);
		} catch {
			// ignore transient shell fetch issues
		}
	}

	$effect(() => {
		if (!machine.machine) {
			dashboardCrops = {};
			cropBaseUrl = null;
			return;
		}

		const baseUrl = currentBackendBaseUrl();
		if (cropBaseUrl === baseUrl) return;
		cropBaseUrl = baseUrl;
		void fetchDashboardCrops(baseUrl);
		void loadMachineSetup(baseUrl);
		void loadDashboardConfig(baseUrl);
	});

	const CAMERA_LABELS: Record<string, string> = {
		feeder: 'Feeder',
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		carousel: 'Carousel',
		classification_channel: 'Classification Channel',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};

	function cameraLabel(role: string): string {
		if (role === 'carousel' && machineSetup === 'classification_channel') {
			return 'Classification Channel';
		}
		return CAMERA_LABELS[role] ?? role;
	}

	onMount(() => {
		if (machine.machine) {
			const baseUrl = currentBackendBaseUrl();
			void fetchDashboardCrops(baseUrl);
			void loadMachineSetup(baseUrl);
			void loadDashboardConfig(baseUrl);
		}
	});
</script>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-6">

	{#if machine.machine}
		<div class="flex h-[calc(100vh-7rem)] min-h-0 gap-3">
				{#if camera_layout === 'split_feeder'}
					{@const has_cls_top = isConfigured('classification_top')}
					{@const has_cls_bottom = isConfigured('classification_bottom')}
					{@const classification_camera = preferredClassificationCamera(has_cls_top, has_cls_bottom)}
					<div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
					<div class="flex min-h-0 flex-1 gap-3">
							<div class="flex-1 min-w-0">
									<CameraFeed
										camera="c_channel_2"
										label={cameraLabel('c_channel_2')}
										crop={cropFor('c_channel_2')}
										controls={["annotations", "zones", "crop", "fullscreen"]}
									/>
								</div>
								<div class="flex-1 min-w-0">
									<CameraFeed
										camera="c_channel_3"
										label={cameraLabel('c_channel_3')}
										crop={cropFor('c_channel_3')}
										controls={["annotations", "zones", "crop", "fullscreen"]}
									/>
								</div>
							</div>
						<div class="flex min-h-0 flex-1 gap-3">
							<div class="flex-1 min-w-0">
									<CameraFeed
										camera={c4CameraRole}
										label={cameraLabel(c4CameraRole)}
										crop={cropFor(c4CameraRole)}
										controls={["annotations", "zones", "crop", "fullscreen"]}
									/>
								</div>
							{#if classification_camera}
								<div class="flex-1 min-w-0">
									<div class="setup-card-shell flex h-full min-h-0 flex-col border">
                                        <div class="setup-card-header flex items-center justify-between px-3 py-2 text-sm">
											<span class="font-medium text-text">Classification</span>
											<div class="flex items-center gap-2">
												{#if has_cls_top && has_cls_bottom}
													<div class="flex items-center gap-3 text-xs font-medium">
														<button
															type="button"
															onclick={() => (classification_view = 'top')}
															class={`border-b-2 pb-1 transition-colors ${classificationTabClass(classification_view === 'top')}`}
														>
															Top
														</button>
														<button
															type="button"
															onclick={() => (classification_view = 'bottom')}
															class={`border-b-2 pb-1 transition-colors ${classificationTabClass(classification_view === 'bottom')}`}
														>
															Bottom
														</button>
													</div>
												{/if}
												<button
													type="button"
													onclick={() => (classification_layer = classification_layer === 'annotated' ? 'raw' : 'annotated')}
													class="p-1 text-text transition-colors hover:bg-white/70"
													title={classification_layer === 'annotated' ? 'Show raw' : 'Show annotations'}
												>
													{#if classification_layer === 'annotated'}
														<Eye size={14} />
													{:else}
														<EyeOff size={14} />
													{/if}
												</button>
											</div>
										</div>
										<div class="min-h-0 flex-1">
											<CameraFeed
												camera={classification_camera}
												label={cameraLabel(classification_camera)}
												crop={cropFor(classification_camera)}
												showHeader={false}
												controls={[]}
												bind:layer={classification_layer}
											/>
										</div>
									</div>
								</div>
							{/if}
						</div>
					</div>
				{:else}
					{@const has_top = isConfigured('classification_top')}
					{@const has_bottom = isConfigured('classification_bottom')}
					{@const classification_camera = preferredClassificationCamera(has_top, has_bottom)}
					{#if classification_camera && ((has_top ? 1 : 0) + (has_bottom ? 1 : 0) === 1)}
						<div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
							<div class="flex-1 min-w-0">
									<CameraFeed
										camera="feeder"
										label={cameraLabel('feeder')}
										crop={cropFor('feeder')}
										controls={["annotations", "zones", "crop", "fullscreen"]}
									/>
								</div>
							<div class="flex-1 min-w-0">
								<CameraFeed
									camera={classification_camera}
									label={cameraLabel(classification_camera)}
									crop={cropFor(classification_camera)}
									controls={["annotations", "crop", "fullscreen"]}
								/>
							</div>
						</div>
					{:else}
						<div class="flex min-h-0 min-w-0 flex-1 gap-3">
							<div class="flex-1 min-w-0">
									<CameraFeed
										camera="feeder"
										label={cameraLabel('feeder')}
										crop={cropFor('feeder')}
										controls={["annotations", "zones", "crop", "fullscreen"]}
									/>
								</div>
							{#if classification_camera}
								<div class="setup-card-shell flex min-h-0 flex-1 flex-col border">
                                    <div class="setup-card-header flex items-center justify-between px-3 py-2 text-sm">
										<span class="font-medium text-text">Classification</span>
										<div class="flex items-center gap-2">
											{#if has_top && has_bottom}
												<div class="flex items-center gap-3 text-xs font-medium">
													<button
														type="button"
														onclick={() => (classification_view = 'top')}
														class={`border-b-2 pb-1 transition-colors ${classificationTabClass(classification_view === 'top')}`}
													>
														Top
													</button>
													<button
														type="button"
														onclick={() => (classification_view = 'bottom')}
														class={`border-b-2 pb-1 transition-colors ${classificationTabClass(classification_view === 'bottom')}`}
													>
														Bottom
													</button>
												</div>
											{/if}
											<button
												type="button"
												onclick={() => (classification_layer = classification_layer === 'annotated' ? 'raw' : 'annotated')}
												class="p-1 text-text transition-colors hover:bg-white/70"
												title={classification_layer === 'annotated' ? 'Show raw' : 'Show annotations'}
											>
												{#if classification_layer === 'annotated'}
													<Eye size={14} />
												{:else}
													<EyeOff size={14} />
												{/if}
											</button>
										</div>
									</div>
									<div class="min-h-0 flex-1">
										<CameraFeed
											camera={classification_camera}
											label={cameraLabel(classification_camera)}
											crop={cropFor(classification_camera)}
											showHeader={false}
											controls={[]}
											bind:layer={classification_layer}
										/>
									</div>
								</div>
							{/if}
						</div>
					{/if}
				{/if}

			<ResizeHandle orientation="vertical" onresize={onSidebarResize} />

			<div class="flex min-h-0 flex-shrink-0 flex-col gap-3 overflow-hidden" style="width: {sidebar_width}px;">
				{#if hardwareState !== 'ready'}
					<div class="shrink-0 border border-border bg-bg px-4 py-3">
						{#if hardwareState === 'standby'}
							<div class="flex items-center justify-between gap-3">
								<div>
									<div class="text-sm font-medium text-text">System Standby</div>
									<div class="text-xs text-text-muted">Press Home to initialize hardware and home all axes.</div>
									{#if startSystemError}
										<div class="mt-1 text-xs text-danger">{startSystemError}</div>
									{/if}
								</div>
								<button
									onclick={startSystem}
									disabled={startingSystem}
									class="shrink-0 cursor-pointer border border-success bg-success px-4 py-1.5 text-sm font-medium text-white hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-50"
								>
									Home
								</button>
							</div>
						{:else if hardwareState === 'homing'}
							<div class="flex items-center gap-3">
								<div class="h-4 w-4 animate-spin border-2 border-primary border-t-transparent" style="border-radius: 50%;"></div>
								<div>
									<div class="text-sm font-medium text-text">Homing...</div>
									<div class="text-xs text-text-muted">{homingStep ?? 'Initializing hardware...'}</div>
								</div>
							</div>
						{:else if hardwareState === 'error'}
							<div class="flex flex-col gap-2">
								<div class="text-sm font-medium text-danger">Hardware Error</div>
								{#if hardwareError}
									<div class="text-xs text-text-muted">{hardwareError}</div>
								{/if}
								<button
									onclick={startSystem}
									disabled={startingSystem}
									class="w-fit cursor-pointer border border-border bg-surface px-3 py-1 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
								>
									Retry
								</button>
							</div>
						{/if}
					</div>
				{/if}
				{#if showSampleCapture}
					<CollapsibleSection title="Sample Capture" storageKey="sampleCapture">
						<SampleCollectionSpeedPanel baseUrl={currentBackendBaseUrl()} {hardwareState} />
					</CollapsibleSection>
				{/if}
				<CollapsibleSection title="Recent Pieces" storageKey="recent" grow>
					<RecentObjects />
				</CollapsibleSection>
				<CollapsibleSection title="Bins" storageKey="bins">
					{#snippet actions()}
						<a href="/profiles" class="text-xs text-text-muted hover:text-text">Profiles</a>
						<a href="/bins" class="text-xs text-text-muted hover:text-text">Bins</a>
					{/snippet}
					<SortingStatusCard />
				</CollapsibleSection>
				<CollapsibleSection title="Runtime" storageKey="runtimeTabs">
					<SidebarBottomTabs />
				</CollapsibleSection>
			</div>
		</div>
	{:else}
		<div class="py-12 text-center text-text-muted">
			No machine selected. Connect to a machine in Settings.
		</div>
	{/if}
	</div>
</div>
