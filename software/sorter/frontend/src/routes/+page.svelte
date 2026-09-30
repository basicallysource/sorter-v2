<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import { getMachineContext, getMachinesContext } from '$lib/machines/context';
	import {
		getBackendHttpBase,
		getBackendWsBase,
		machineHttpBaseUrlFromWsUrl,
		machineWsUrlFromHttpBaseUrl
	} from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import IncidentCard, { type IncidentCardData } from '$lib/components/IncidentCard.svelte';
	import CameraChannelControls from '$lib/components/CameraChannelControls.svelte';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import CollapsibleSection from '$lib/components/CollapsibleSection.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import RuntimeStats, { RUNTIME_SPANS, type RuntimeSpan } from '$lib/components/RuntimeStats.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import { buildDashboardFeedCrops, type DashboardFeedCrop } from '$lib/dashboard/crops';
	import House from '@lucide/svelte/icons/house';
	import Plug from '@lucide/svelte/icons/plug';

	const machine = getMachineContext();
	const manager = getMachinesContext();

	let dashboardCrops = $state<Record<string, DashboardFeedCrop | null>>({});
	let cropBaseUrl = $state<string | null>(null);
	let startSystemError = $state<string | null>(null);
	let startSystemPending = $state(false);
	let runtimeSpan = $state<RuntimeSpan>('1h');

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	const hardwareState = $derived(machine.machine?.systemStatus?.hardware_state ?? 'standby');
	const hardwareFault = $derived(machine.machine?.systemStatus?.hardware_error ?? null);
	const hardwareError = $derived(startSystemError ?? hardwareFault?.message ?? null);
	const homingStep = $derived(machine.machine?.systemStatus?.homing_step ?? null);
	const noPowerDevelopmentMode = $derived(
		machine.machine?.systemStatus?.no_power_development_mode ?? false
	);
	const startingSystem = $derived(hardwareState === 'homing' || startSystemPending);
	const runtimeStats = $derived((machine.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const incidentCard = $derived(
		(runtimeStats.incident_card ?? null) as IncidentCardData | null
	);

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
					typeof payload?.message === 'string' ? payload.message : 'Starting safe recovery...',
				no_power_development_mode: noPowerDevelopmentMode
			});
			const wsUrl = machineWsUrlFromHttpBaseUrl(baseUrl) ?? `${getBackendWsBase()}/ws`;
			manager.ensureConnected(wsUrl);
			manager.queueSystemStatusRefreshes(baseUrl);
		} catch (e: any) {
			startSystemError = e?.message ?? 'Failed to recover system';
			manager.queueSystemStatusRefreshes(baseUrl);
		} finally {
			startSystemPending = false;
		}
	}

	function cropFor(role: string): DashboardFeedCrop | null {
		if (role === 'classification_channel' || role === 'carousel') {
			return dashboardCrops.classification_channel ?? dashboardCrops.carousel ?? null;
		}
		return dashboardCrops[role] ?? null;
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

	// A brand-new machine should open on the setup wizard, not an empty Dashboard.
	// Once per browser session, so Dashboard stays reachable while setting up.
	async function openSetupIfNew(baseUrl: string) {
		try {
			if (sessionStorage.getItem('sorter.setup-offered')) return;
			sessionStorage.setItem('sorter.setup-offered', '1');
			const res = await fetch(`${baseUrl}/api/setup-wizard/needed`);
			if (res.ok && (await res.json())?.needed) await goto('/setup');
		} catch {
			// no storage or no backend yet: stay on the Dashboard
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
		void openSetupIfNew(baseUrl);
	});

	const CAMERA_LABELS: Record<string, string> = {
		feeder: 'Feeder',
		c_channel_2: 'C-channel 2',
		c_channel_3: 'C-channel 3',
		carousel: 'Classification channel',
		classification_channel: 'Classification channel'
	};

	function cameraLabel(role: string): string {
		return CAMERA_LABELS[role] ?? role;
	}

	onMount(() => {
		if (machine.machine) {
			const baseUrl = currentBackendBaseUrl();
			void fetchDashboardCrops(baseUrl);
		}
	});
</script>

<svelte:head><title>Sorter - Dashboard</title></svelte:head>

<AppShell fit>
	{#if machine.machine}
		<!-- From lg up the page is the window. The row is a size container, so the
		     cameras' width comes from its height: --feed is a picture's height over
		     its width (9 / 16 for a 16:9 feed), and the group is as wide as the
		     height allows, so every picture fills its tile and none has a bar. The
		     column beside takes the rest of the width. See the design system's
		     docs/layout.md, the dashboard layout. -->
		<div
			class="flex min-h-0 flex-1 flex-col gap-(--gap-panels) p-4 sm:p-6 lg:flex-row lg:justify-center lg:[container-type:size]"
			style="--feed: 0.5625"
		>
			<div
				class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 lg:w-(--cameras) lg:shrink-0 lg:self-start"
				style="--cameras: min(100cqw - 19rem - var(--gap-panels), (100cqh - 2 * var(--size-control-lg) - (1 - var(--feed) / 2) * var(--gap-panels)) / (1.5 * var(--feed)))"
			>
				<CameraFeed
					camera="c_channel_2"
					label={cameraLabel('c_channel_2')}
					crop={cropFor('c_channel_2')}
					controls={['annotations', 'crop', 'fullscreen']}
					class="@container"
				>
					{#snippet actions()}
						<CameraChannelControls stepperKey="c_channel_2" />
					{/snippet}
				</CameraFeed>
				<CameraFeed
					camera="c_channel_3"
					label={cameraLabel('c_channel_3')}
					crop={cropFor('c_channel_3')}
					controls={['annotations', 'crop', 'fullscreen']}
					class="@container"
				>
					{#snippet actions()}
						<CameraChannelControls stepperKey="c_channel_3" />
					{/snippet}
				</CameraFeed>
				<CameraFeed
					camera="classification_channel"
					label={cameraLabel('classification_channel')}
					crop={cropFor('classification_channel')}
					controls={['annotations', 'crop', 'fullscreen']}
					class="@container md:col-span-2"
				>
					{#snippet actions()}
						<CameraChannelControls stepperKey="c_channel_4" />
					{/snippet}
				</CameraFeed>
			</div>

			<!-- Beside the cameras from lg up, from 19rem to 40rem wide. On a phone this
			     wrapper disappears, so its parts take their place in the page's own order:
			     the status and any incident first, then the cameras, then the pieces and
			     the runtime. -->
			<div
				class="contents lg:flex lg:max-w-160 lg:min-w-76 lg:min-h-0 lg:flex-1 lg:flex-col lg:gap-(--gap-panels) lg:overflow-y-auto"
			>
				{#if hardwareState === 'standby' || hardwareState === 'homing' || hardwareState === 'error'}
					<section class="shrink-0 rounded-panel bg-surface p-(--pad-panel) max-lg:order-first">
						{#if hardwareState === 'standby'}
							<div class="flex items-start justify-between gap-4">
								<div class="min-w-0">
									<div class="flex items-center gap-2">
										<span class="text-base font-semibold text-ink">Standby</span>
										<Badge tone="warning" dot>Not homed</Badge>
									</div>
									<p class="mt-1 text-sm text-ink-muted">
										{#if noPowerDevelopmentMode}
											Sim home runs the normal recovery and skips only the physical homing.
										{:else}
											Home starts the hardware and moves every axis to its zero.
										{/if}
									</p>
									{#if startSystemError}
										<p class="mt-1 text-sm text-danger-ink">{startSystemError}</p>
									{/if}
								</div>
								<div class="flex shrink-0 items-center gap-2">
									{#if noPowerDevelopmentMode}
										<Button onclick={startSystem} disabled={startingSystem}>Sim home</Button>
									{/if}
									<Button
										variant="primary"
										icon={House}
										loading={startSystemPending}
										disabled={startingSystem}
										onclick={startSystem}
									>
										Home
									</Button>
								</div>
							</div>
						{:else if hardwareState === 'homing'}
							<div class="flex items-center gap-3">
								<Spinner size={16} class="text-primary-ink" />
								<div class="min-w-0">
									<div class="text-base font-semibold text-ink">Homing</div>
									<p class="text-sm text-ink-muted">{homingStep ?? 'Starting the hardware'}</p>
								</div>
							</div>
						{:else}
							<div class="flex items-start justify-between gap-4">
								<div class="min-w-0">
									<div class="flex items-center gap-2">
										<span class="text-base font-semibold text-ink">
											{hardwareFault?.title ?? 'Hardware error'}
										</span>
										<Badge tone="danger" dot>Stopped</Badge>
									</div>
									{#if hardwareError}
										<p class="mt-1 text-sm break-words text-ink-muted">{hardwareError}</p>
									{/if}
								</div>
								<Button onclick={startSystem} disabled={startingSystem}>Retry</Button>
							</div>
						{/if}
					</section>
				{/if}

				{#if incidentCard}
					<IncidentCard card={incidentCard} baseUrl={currentBackendBaseUrl()} />
				{/if}

				<div class="max-lg:order-last lg:contents">
					<CollapsibleSection title="Recent pieces" storageKey="recent" grow>
						<RecentObjects />
					</CollapsibleSection>
				</div>
				<div class="max-lg:order-last lg:contents">
					<CollapsibleSection title="Runtime" storageKey="runtimeTabs">
						{#snippet actions()}
							<SegmentedControl bind:value={runtimeSpan} options={RUNTIME_SPANS} label="Time span" size="sm" />
						{/snippet}
						<RuntimeStats span={runtimeSpan} />
					</CollapsibleSection>
				</div>
			</div>
		</div>
	{:else}
		<div class="p-4 sm:p-6">
			<EmptyState icon={Plug} title="No machine selected">
				Connect to a machine in Settings.
			</EmptyState>
		</div>
	{/if}
</AppShell>
