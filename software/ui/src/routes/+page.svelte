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

	const SIDEBAR_MIN = 300;
	const SIDEBAR_MAX = 900;
	const SIDEBAR_DEFAULT = 420;

	const machine = getMachineContext();

	let camera_layout = $state<string>('default');
	let cameraConfig = $state<Record<string, number | string | null>>({});
	let sidebar_width = $state(SIDEBAR_DEFAULT);
	let hardwareState = $state<string>('standby');
	let hardwareError = $state<string | null>(null);
	let startingSystem = $state(false);

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
		return cameraConfig[role] !== null && cameraConfig[role] !== undefined;
	}

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
				{@const has_cls_top = isConfigured('classification_top') || machine.frames.has('classification_top')}
				{@const has_cls_bottom = isConfigured('classification_bottom') || machine.frames.has('classification_bottom')}
				<div class="flex min-w-0 flex-1 flex-col gap-3">
					<div class="flex flex-[7] gap-3">
						<div class="flex-1">
							<CameraFeed camera="c_channel_2" label={CAMERA_LABELS.c_channel_2} />
						</div>
						<div class="flex-1">
							<CameraFeed camera="c_channel_3" label={CAMERA_LABELS.c_channel_3} />
						</div>
					</div>
					<div class="flex flex-[3] gap-3">
						<div class="flex-1">
							<CameraFeed camera="carousel" label={CAMERA_LABELS.carousel} />
						</div>
						{#if has_cls_top}
							<div class="flex-1">
								<CameraFeed camera="classification_top" label={CAMERA_LABELS.classification_top} />
							</div>
						{/if}
						{#if has_cls_bottom}
							<div class="flex-1">
								<CameraFeed camera="classification_bottom" label={CAMERA_LABELS.classification_bottom} />
							</div>
						{/if}
					</div>
				</div>
			{:else}
				{@const has_top = machine.frames.has('classification_top')}
				{@const has_bottom = machine.frames.has('classification_bottom')}
				{@const single_classification = (has_top ? 1 : 0) + (has_bottom ? 1 : 0) === 1}
				{#if single_classification}
					<div class="flex min-w-0 flex-1 flex-col gap-3">
						<div class="flex-1">
							<CameraFeed camera="feeder" label={CAMERA_LABELS.feeder} />
						</div>
						<div class="flex-1">
							{#if has_top}
								<CameraFeed camera="classification_top" label={CAMERA_LABELS.classification_top} />
							{:else}
								<CameraFeed camera="classification_bottom" label={CAMERA_LABELS.classification_bottom} />
							{/if}
						</div>
					</div>
				{:else}
					<div class="flex min-w-0 flex-1 gap-3">
						<div class="flex-1">
							<CameraFeed camera="feeder" label={CAMERA_LABELS.feeder} />
						</div>
						<div class="flex flex-1 flex-col gap-3">
							<div class="flex-1">
								<CameraFeed camera="classification_top" label={CAMERA_LABELS.classification_top} />
							</div>
							<div class="flex-1">
								<CameraFeed camera="classification_bottom" label={CAMERA_LABELS.classification_bottom} />
							</div>
						</div>
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
								<div class="h-4 w-4 animate-spin border-2 border-[#0055BF] border-t-transparent" style="border-radius: 50%;"></div>
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
