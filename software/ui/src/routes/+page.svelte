<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import ResizeHandle from '$lib/components/ResizeHandle.svelte';
	import RuntimeStats from '$lib/components/RuntimeStats.svelte';
	import SortingStatusCard from '$lib/components/SortingStatusCard.svelte';
	import { buildDashboardFeedCrops, type DashboardFeedCrop } from '$lib/dashboard/crops';
	import { Eye, EyeOff } from 'lucide-svelte';

	const SIDEBAR_MIN = 300;
	const SIDEBAR_MAX = 900;
	const SIDEBAR_DEFAULT = 420;

	const machine = getMachineContext();

	let camera_layout = $state<string>('default');
	let cameraConfig = $state<Record<string, number | string | null>>({});
	let dashboardCrops = $state<Record<string, DashboardFeedCrop | null>>({});
	let cropBaseUrl = $state<string | null>(null);
	let sidebar_width = $state(SIDEBAR_DEFAULT);
	let hardwareState = $state<string>('standby');
	let hardwareError = $state<string | null>(null);
	let startingSystem = $state(false);
	let classification_view = $state<'top' | 'bottom'>('top');
	let classification_annotated = $state(true);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	function onSidebarResize(delta: number) {
		sidebar_width = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, sidebar_width - delta));
	}

	async function fetchState() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/state`);
			if (res.ok) {
				const data = await res.json();
				camera_layout = data.camera_layout ?? 'default';
			}
		} catch {
			// ignore
		}
	}

	let homingStep = $state<string | null>(null);

	async function fetchSystemStatus() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/status`);
			if (res.ok) {
				const data = await res.json();
				hardwareState = data.hardware_state ?? 'standby';
				hardwareError = data.hardware_error ?? null;
				homingStep = data.homing_step ?? null;
				startingSystem = hardwareState === 'homing';
			}
		} catch {
			// ignore
		}
	}

	async function startSystem() {
		startingSystem = true;
		hardwareError = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/home`, { method: 'POST' });
			if (res.ok) {
				hardwareState = 'homing';
			}
		} catch (e: any) {
			hardwareError = e.message ?? 'Failed to home system';
			startingSystem = false;
		}
	}

	async function fetchCameraConfig() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/cameras/config`);
			if (res.ok) {
				cameraConfig = await res.json();
			}
		} catch {
			// ignore
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
	});

	const CAMERA_LABELS: Record<string, string> = {
		feeder: 'Feeder',
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		carousel: 'Carousel',
		classification_top: 'Classification Top',
		classification_bottom: 'Classification Bottom'
	};

	onMount(() => {
		void fetchState();
		void fetchCameraConfig();
		void fetchSystemStatus();
		if (machine.machine) {
			void fetchDashboardCrops(currentBackendBaseUrl());
		}
		const interval = setInterval(() => {
			void fetchState();
			void fetchCameraConfig();
			void fetchSystemStatus();
		}, 2000);
		return () => clearInterval(interval);
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
									label={CAMERA_LABELS.c_channel_2}
									crop={cropFor('c_channel_2')}
								/>
							</div>
							<div class="flex-1 min-w-0">
								<CameraFeed
									camera="c_channel_3"
									label={CAMERA_LABELS.c_channel_3}
									crop={cropFor('c_channel_3')}
								/>
							</div>
						</div>
						<div class="flex min-h-0 flex-1 gap-3">
							<div class="flex-1 min-w-0">
								<CameraFeed
									camera="carousel"
									label={CAMERA_LABELS.carousel}
									crop={cropFor('carousel')}
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
													onclick={() => (classification_annotated = !classification_annotated)}
													class="p-1 text-text transition-colors hover:bg-white/70"
													title={classification_annotated ? 'Show raw' : 'Show annotations'}
												>
													{#if classification_annotated}
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
												label={CAMERA_LABELS[classification_camera]}
												crop={cropFor(classification_camera)}
												showHeader={false}
												bind:annotated={classification_annotated}
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
									label={CAMERA_LABELS.feeder}
									crop={cropFor('feeder')}
								/>
							</div>
							<div class="flex-1 min-w-0">
								<CameraFeed
									camera={classification_camera}
									label={CAMERA_LABELS[classification_camera]}
									crop={cropFor(classification_camera)}
								/>
							</div>
						</div>
					{:else}
						<div class="flex min-h-0 min-w-0 flex-1 gap-3">
							<div class="flex-1 min-w-0">
								<CameraFeed
									camera="feeder"
									label={CAMERA_LABELS.feeder}
									crop={cropFor('feeder')}
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
												onclick={() => (classification_annotated = !classification_annotated)}
												class="p-1 text-text transition-colors hover:bg-white/70"
												title={classification_annotated ? 'Show raw' : 'Show annotations'}
											>
												{#if classification_annotated}
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
											label={CAMERA_LABELS[classification_camera]}
											crop={cropFor(classification_camera)}
											showHeader={false}
											bind:annotated={classification_annotated}
										/>
									</div>
								</div>
							{/if}
						</div>
					{/if}
				{/if}

			<ResizeHandle orientation="vertical" onresize={onSidebarResize} />

			<div class="flex min-h-0 flex-shrink-0 flex-col gap-3" style="width: {sidebar_width}px;">
				{#if hardwareState !== 'ready'}
					<div class="shrink-0 border border-border bg-bg px-4 py-3">
						{#if hardwareState === 'standby'}
							<div class="flex items-center justify-between gap-3">
								<div>
									<div class="text-sm font-medium text-text">System Standby</div>
									<div class="text-xs text-text-muted">Press Home to initialize hardware and home all axes.</div>
								</div>
								<button
									onclick={startSystem}
									disabled={startingSystem}
									class="shrink-0 cursor-pointer border border-[#00852B] bg-[#00852B] px-4 py-1.5 text-sm font-medium text-white hover:bg-[#00852B]/90 disabled:cursor-not-allowed disabled:opacity-50"
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
								<div class="text-sm font-medium text-[#D01012]">Hardware Error</div>
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
				<div class="min-h-0 flex-1">
					<RecentObjects />
				</div>
				<div class="shrink-0">
					<SortingStatusCard />
				</div>
				<div class="min-h-0 flex-1 overflow-y-auto">
					<RuntimeStats />
				</div>
			</div>
		</div>
	{:else}
		<div class="py-12 text-center text-text-muted">
			No machine selected. Connect to a machine in Settings.
		</div>
	{/if}
	</div>
</div>
