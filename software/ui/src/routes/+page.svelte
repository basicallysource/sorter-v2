<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';

	const machine = getMachineContext();

	let camera_layout = $state<string>('default');
	let cameraConfig = $state<Record<string, number | string | null>>({});

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
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
		const interval = setInterval(() => {
			void fetchState();
			void fetchCameraConfig();
		}, 3000);
		return () => clearInterval(interval);
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<AppHeader />

	{#if machine.machine}
		<div class="flex h-[calc(100vh-7rem)] gap-3">
			{#if camera_layout === 'split_feeder'}
				{@const has_cls_top = isConfigured('classification_top') || machine.frames.has('classification_top')}
				{@const has_cls_bottom = isConfigured('classification_bottom') || machine.frames.has('classification_bottom')}
				{@const has_secondary = has_cls_top || has_cls_bottom}
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
			<div class="w-64 flex-shrink-0">
				<RecentObjects />
			</div>
		</div>
	{:else}
		<div class="dark:text-text-muted-dark py-12 text-center text-text-muted">
			No machine selected. Connect to a machine in Settings.
		</div>
	{/if}
</div>
