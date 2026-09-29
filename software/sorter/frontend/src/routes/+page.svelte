<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import { getMachineContext, getMachinesContext } from '$lib/machines/context';
	import {
		getBackendHttpBase,
		getBackendWsBase,
		machineHttpBaseUrlFromWsUrl,
		machineWsUrlFromHttpBaseUrl
	} from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import CameraChannelControls from '$lib/components/CameraChannelControls.svelte';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import CollapsibleSection from '$lib/components/CollapsibleSection.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import ResizeHandle from '$lib/components/ResizeHandle.svelte';
	import SidebarBottomTabs from '$lib/components/SidebarBottomTabs.svelte';
	import { buildDashboardFeedCrops, type DashboardFeedCrop } from '$lib/dashboard/crops';
	import Check from '@lucide/svelte/icons/check';
	import House from '@lucide/svelte/icons/house';
	import Plug from '@lucide/svelte/icons/plug';
	import Info from '@lucide/svelte/icons/info';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import X from '@lucide/svelte/icons/x';

	const SIDEBAR_MIN = 300;
	const SIDEBAR_MAX = 900;
	const SIDEBAR_DEFAULT = 420;
	const EXIT_STUCK_INCIDENT_KIND = 'exit_stuck';
	const machine = getMachineContext();
	const manager = getMachinesContext();

	let dashboardCrops = $state<Record<string, DashboardFeedCrop | null>>({});
	let cropBaseUrl = $state<string | null>(null);
	let sidebar_width = $state(SIDEBAR_DEFAULT);
	let startSystemError = $state<string | null>(null);
	let startSystemPending = $state(false);
	let exitIncidentActionPending = $state(false);
	let exitIncidentActionError = $state<string | null>(null);
	let stallIncidentActionPending = $state(false);
	let stallIncidentActionError = $state<string | null>(null);
	let rehomeIncidentActionPending = $state(false);
	let rehomeIncidentActionError = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function onSidebarResize(delta: number) {
		sidebar_width = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, sidebar_width - delta));
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
	const exitIncident = $derived(normalizeExitIncident(runtimeStats.active_incident));
	const stallIncident = $derived(stepperStallIncident(runtimeStats.active_incident));
	const needsHomingIncident = $derived(chuteNeedsHomingIncident(runtimeStats.active_incident));

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

	function stepperStallIncident(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object') return null;
		const incident = value as Record<string, unknown>;
		return incident.kind === 'stepper_stall' ? incident : null;
	}

	function chuteNeedsHomingIncident(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object') return null;
		const incident = value as Record<string, unknown>;
		return incident.kind === 'chute_needs_homing' ? incident : null;
	}

	function stallIncidentSteppersLabel(incident: Record<string, unknown> | null): string {
		const steppers = incident?.steppers;
		if (Array.isArray(steppers) && steppers.length > 0) {
			return steppers.filter((s) => typeof s === 'string').join(', ');
		}
		return incidentString(incident, 'channel', 'a motor');
	}

	async function postStallAction(path: string, fallbackError: string): Promise<string | null> {
		try {
			const response = await fetch(`${currentBackendBaseUrl()}${path}`, { method: 'POST' });
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			if (!response.ok || payload?.ok === false) {
				return typeof payload?.detail === 'string' ? payload.detail : fallbackError;
			}
			return null;
		} catch (e: any) {
			return e?.message ?? fallbackError;
		}
	}

	async function acknowledgeStallIncident() {
		if (stallIncidentActionPending) return;
		stallIncidentActionPending = true;
		stallIncidentActionError = null;
		stallIncidentActionError = await postStallAction('/stall-incident/clear', 'Could not clear stall');
		stallIncidentActionPending = false;
	}

	async function rehomeAfterStall() {
		if (stallIncidentActionPending) return;
		stallIncidentActionPending = true;
		stallIncidentActionError = null;
		stallIncidentActionError = await postStallAction('/stall-incident/rehome', 'Could not re-home');
		stallIncidentActionPending = false;
	}

	async function rehomeChute() {
		if (rehomeIncidentActionPending) return;
		rehomeIncidentActionPending = true;
		rehomeIncidentActionError = null;
		rehomeIncidentActionError = await postStallAction(
			'/stall-incident/rehome',
			'Could not re-home'
		);
		rehomeIncidentActionPending = false;
	}

	function normalizeExitIncident(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object') return null;
		const incident = value as Record<string, unknown>;
		return incident.kind === EXIT_STUCK_INCIDENT_KIND ||
			incident.kind === 'feeder_jam' ||
			incident.kind === 'distribution_chute_jam' ||
			incident.kind === 'distribution_servo_bus_offline' ||
			incident.kind === 'distribution_no_bin_available' ||
			incident.kind === 'classification_unresolved' ||
			incident.kind === 'classification_multi_drop_collision' ||
			incident.kind === 'classification_intake_request_timeout' ||
			incident.kind === 'classification_track_lost'
			? incident
			: null;
	}

	function incidentString(
		incident: Record<string, unknown> | null,
		key: string,
		fallback = ''
	): string {
		const value = incident?.[key];
		return typeof value === 'string' && value.length > 0 ? value : fallback;
	}

	function incidentNumber(incident: Record<string, unknown> | null, key: string): number | null {
		const value = incident?.[key];
		return typeof value === 'number' && Number.isFinite(value) ? value : null;
	}

	let incidentDetailsOpen = $state(false);
	let incidentDetailsTarget = $state<Record<string, unknown> | null>(null);
	let incidentDetailsTitle = $state('Incident details');

	function openIncidentDetails(incident: Record<string, unknown> | null, title: string) {
		if (!incident) return;
		incidentDetailsTarget = incident;
		incidentDetailsTitle = title || 'Incident details';
		incidentDetailsOpen = true;
	}

	function formatIncidentDetailValue(key: string, value: unknown): string {
		if (value === null || value === undefined || value === '') return '—';
		if (typeof value === 'number') {
			if (!Number.isFinite(value)) return String(value);
			if ((key === 'triggered_at' || key.endsWith('_at')) && value > 1_000_000_000) {
				return new Date(value * 1000).toLocaleString();
			}
			return Number.isInteger(value) ? String(value) : Number(value.toFixed(3)).toString();
		}
		if (typeof value === 'boolean') return value ? 'true' : 'false';
		if (typeof value === 'string') return value;
		try {
			return JSON.stringify(value);
		} catch {
			return String(value);
		}
	}

	function incidentDetailEntries(
		incident: Record<string, unknown> | null
	): Array<{ key: string; value: string }> {
		if (!incident) return [];
		return Object.keys(incident)
			.sort((a, b) => a.localeCompare(b))
			.map((key) => ({ key, value: formatIncidentDetailValue(key, incident[key]) }));
	}

	function isC4StallWatchdogIncident(incident: Record<string, unknown> | null): boolean {
		return incidentString(incident, 'source_kind') === 'c4_stall_watchdog';
	}

	function exitIncidentStatusLabel(incident: Record<string, unknown> | null): string {
		return exitIncidentMotionBusy(incident) ? 'Running' : 'Waiting';
	}

	function exitIncidentMotionBusy(incident: Record<string, unknown> | null): boolean {
		return incidentString(incident, 'status') === 'auto_release_running';
	}

	function exitIncidentApiBase(incident: Record<string, unknown>): string {
		if (incident.kind === 'feeder_jam') {
			return `${currentBackendBaseUrl()}/api/feeder/jam-incident`;
		}
		if (
			incident.kind === 'distribution_chute_jam' ||
			incident.kind === 'distribution_servo_bus_offline' ||
			incident.kind === 'distribution_no_bin_available'
		) {
			return `${currentBackendBaseUrl()}/api/distribution/incident`;
		}
		if (
			incident.kind === 'classification_unresolved' ||
			incident.kind === 'classification_multi_drop_collision' ||
			incident.kind === 'classification_intake_request_timeout' ||
			incident.kind === 'classification_track_lost'
		) {
			return `${currentBackendBaseUrl()}/api/classification-channel/fallback-incident`;
		}
		return `${currentBackendBaseUrl()}/api/classification-channel/exit-incident`;
	}

	function exitIncidentActionBody(
		incident: Record<string, unknown>
	): Record<string, string | number> {
		if (
			incident.kind === 'feeder_jam' ||
			incident.kind === 'distribution_chute_jam' ||
			incident.kind === 'distribution_servo_bus_offline' ||
			incident.kind === 'distribution_no_bin_available'
		) {
			const body: Record<string, string | number> = {
				channel: incidentString(incident, 'channel')
			};
			const globalId =
				incidentNumber(incident, 'global_id') ?? incidentNumber(incident, 'track_id');
			if (globalId !== null) body.global_id = Math.round(globalId);
			return body;
		}
		return { piece_uuid: incidentString(incident, 'piece_uuid') };
	}

	function exitIncidentTitle(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'distribution_chute_jam') {
			return 'Chute jam';
		}
		if (incident?.kind === 'distribution_servo_bus_offline') {
			return 'Servo bus offline';
		}
		if (incident?.kind === 'distribution_no_bin_available') {
			return 'No bin available';
		}
		if (incident?.kind === 'classification_unresolved') {
			return 'Classification unresolved';
		}
		if (incident?.kind === 'classification_multi_drop_collision') {
			return 'Multi-drop collision';
		}
		if (incident?.kind === 'classification_intake_request_timeout') {
			return 'Intake request timeout';
		}
		if (incident?.kind === 'classification_track_lost') {
			return 'Track lost';
		}
		if (incident?.kind === 'feeder_jam') {
			return 'Feeder jam';
		}
		return 'Exit stuck';
	}

	function exitIncidentScopeLabel(incident: Record<string, unknown> | null): string {
		const role = incidentString(incident, 'role');
		const channel = incidentString(incident, 'channel');
		if (role === 'c_channel_2' || channel === 'c2') return 'C2';
		if (role === 'c_channel_3' || channel === 'c3') return 'C3';
		if (channel === 'distribution' || role.startsWith('distribution_')) return 'Distribution';
		if (role === 'carousel' || channel === 'c4') return 'C4';
		return '';
	}

	function exitIncidentDescription(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'feeder_jam') {
			return incidentString(
				incident,
				'operator_message',
				'A piece is jammed at a feeder hand-off. Clear the jam to continue.'
			);
		}
		if (incident?.kind === 'distribution_chute_jam') {
			return 'The distribution chute did not finish moving.';
		}
		if (incident?.kind === 'distribution_servo_bus_offline') {
			return 'The distribution servo bus is not responding.';
		}
		if (incident?.kind === 'distribution_no_bin_available') {
			return 'No matching bin is available for the piece.';
		}
		if (incident?.kind === 'classification_unresolved') {
			return 'A piece reached the drop point without a resolved classification.';
		}
		if (incident?.kind === 'classification_multi_drop_collision') {
			return 'Multiple pieces reached the drop point together.';
		}
		if (incident?.kind === 'classification_intake_request_timeout') {
			return 'C4 requested a piece, but no handoff arrived.';
		}
		if (incident?.kind === 'classification_track_lost') {
			return 'A tracked piece disappeared before the expected drop flow completed.';
		}
		return 'The classification channel stopped making progress with a piece on it. Remove the piece (or clear the jam), then resolve to resume.';
	}

	function exitIncidentPrimaryMetricLabel(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'distribution_no_bin_available') return 'Category';
		if (incident?.kind === 'classification_intake_request_timeout') return 'Timeout';
		if (incident?.kind === 'classification_track_lost') return 'Track';
		if (
			incident?.kind === 'classification_unresolved' ||
			incident?.kind === 'classification_multi_drop_collision'
		)
			return 'Status';
		if (incident?.kind === 'distribution_chute_jam') return 'Elapsed';
		if (incident?.kind === 'distribution_servo_bus_offline') return 'Offline';
		return 'Stalled';
	}

	function exitIncidentPrimaryMetricValue(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'feeder_jam') {
			const stalled = incidentNumber(incident, 'no_progress_ms');
			return stalled === null ? '-' : `${stalled.toFixed(0)} ms`;
		}
		if (incident?.kind === 'distribution_chute_jam') {
			const elapsed = incidentNumber(incident, 'elapsed_ms');
			return elapsed === null ? '-' : `${elapsed.toFixed(0)} ms`;
		}
		if (incident?.kind === 'distribution_servo_bus_offline') {
			const layers = incident.offline_layers;
			return Array.isArray(layers) && layers.length > 0 ? layers.join(', ') : 'Bus';
		}
		if (incident?.kind === 'distribution_no_bin_available') {
			return incidentString(incident, 'category_id', '-');
		}
		if (incident?.kind === 'classification_intake_request_timeout') {
			const timeout = incidentNumber(incident, 'timeout_ms');
			return timeout === null ? '-' : `${timeout.toFixed(0)} ms`;
		}
		if (incident?.kind === 'classification_track_lost') {
			const trackId =
				incidentNumber(incident, 'tracked_global_id') ?? incidentNumber(incident, 'track_id');
			return trackId === null ? '-' : `#${trackId.toFixed(0)}`;
		}
		if (
			incident?.kind === 'classification_unresolved' ||
			incident?.kind === 'classification_multi_drop_collision'
		) {
			return incidentString(incident, 'classification_status', '-');
		}
		const stalled = incidentNumber(incident, 'stalled_ms');
		return stalled === null ? '-' : `${(stalled / 1000).toFixed(0)} s`;
	}

	function exitIncidentSecondaryMetricLabel(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'distribution_no_bin_available') return 'Piece';
		if (incident?.kind === 'classification_intake_request_timeout') return 'Detail';
		if (incident?.kind === 'classification_track_lost') return 'Piece';
		if (
			incident?.kind === 'classification_unresolved' ||
			incident?.kind === 'classification_multi_drop_collision'
		)
			return 'Reason';
		if (
			incident?.kind === 'distribution_chute_jam' ||
			incident?.kind === 'distribution_servo_bus_offline'
		)
			return 'Detail';
		if (incident?.kind === 'feeder_jam') return 'Nudges';
		return 'State';
	}

	function exitIncidentSecondaryMetricValue(incident: Record<string, unknown> | null): string {
		if (
			incident?.kind === 'distribution_chute_jam' ||
			incident?.kind === 'distribution_servo_bus_offline'
		) {
			return incidentString(incident, 'detail', '-');
		}
		if (incident?.kind === 'distribution_no_bin_available') {
			return incidentString(incident, 'piece_short', '-');
		}
		if (incident?.kind === 'classification_intake_request_timeout') {
			return incidentString(incident, 'detail', incidentString(incident, 'rule', '-'));
		}
		if (incident?.kind === 'classification_track_lost') {
			return incidentString(incident, 'piece_short', incidentString(incident, 'reason', '-'));
		}
		if (
			incident?.kind === 'classification_unresolved' ||
			incident?.kind === 'classification_multi_drop_collision'
		) {
			return incidentString(incident, 'reason', '-');
		}
		if (incident?.kind === 'feeder_jam') {
			return String(incidentNumber(incident, 'nudge_attempts') ?? '-');
		}
		return incidentString(incident, 'stalled_state', '-');
	}

	async function postExitIncidentAction(action: 'clear' | 'auto-resolve') {
		const incident = exitIncident;
		if (!incident || exitIncidentActionPending) return;
		if (action === 'auto-resolve' && !isC4StallWatchdogIncident(incident)) return;
		exitIncidentActionPending = true;
		exitIncidentActionError = null;
		try {
			const response = await fetch(`${exitIncidentApiBase(incident)}/${action}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(exitIncidentActionBody(incident))
			});
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			if (!response.ok || payload?.ok === false) {
				const detail = payload?.detail;
				throw new Error(typeof detail === 'string' ? detail : `Could not ${action} exit incident`);
			}
		} catch (e: any) {
			exitIncidentActionError = e?.message ?? `Could not ${action} exit incident`;
		} finally {
			exitIncidentActionPending = false;
		}
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

{#snippet incidentDetails(incident: Record<string, unknown>, title: string)}
	<Button variant="ghost" icon={Info} class="ml-auto" onclick={() => openIncidentDetails(incident, title)}>
		Details
	</Button>
{/snippet}

<AppShell fit>
	{#if machine.machine}
		<div class="flex min-h-0 flex-1 flex-col gap-(--gap-panels) p-4 sm:p-6 lg:flex-row lg:gap-2">
			<div class="grid grid-cols-1 min-h-0 min-w-0 flex-1 gap-(--gap-panels) md:grid-cols-2 lg:grid-rows-2">
				<CameraFeed
					camera="c_channel_2"
					label={cameraLabel('c_channel_2')}
					crop={cropFor('c_channel_2')}
					controls={['annotations', 'crop', 'fullscreen']}
					fill
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
					fill
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
					fill
					class="md:col-span-2"
				>
					{#snippet actions()}
						<CameraChannelControls stepperKey="c_channel_4" />
					{/snippet}
				</CameraFeed>
			</div>

			<div class="hidden lg:flex">
				<ResizeHandle orientation="vertical" onresize={onSidebarResize} />
			</div>

			<!-- Beside the cameras from lg up. On a phone this wrapper disappears, so its
			     parts take their place in the page's own order: the status and any
			     incident first, then the cameras, then the pieces and the runtime. -->
			<div
				class="contents min-h-0 w-full shrink-0 flex-col gap-(--gap-panels) lg:flex lg:w-(--sidebar) lg:overflow-y-auto"
				style:--sidebar="{sidebar_width}px"
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

				{#if exitIncident}
					<Alert tone="warning" title={exitIncidentTitle(exitIncident)} class="shrink-0 max-lg:order-first">
						<div class="flex flex-wrap items-center gap-1.5">
							{#if exitIncidentScopeLabel(exitIncident)}
								<Badge>{exitIncidentScopeLabel(exitIncident)}</Badge>
							{/if}
							<Badge tone="warning">{exitIncidentStatusLabel(exitIncident)}</Badge>
						</div>
						<p class="mt-1.5">{exitIncidentDescription(exitIncident)}</p>
						{#if incidentString(exitIncident, 'operator_message')}
							<p class="mt-1.5 font-medium">{incidentString(exitIncident, 'operator_message')}</p>
						{/if}
						<dl class="mt-3 grid grid-cols-2 gap-3">
							<div>
								<dt class="text-ink-muted">{exitIncidentPrimaryMetricLabel(exitIncident)}</dt>
								<dd class="num">{exitIncidentPrimaryMetricValue(exitIncident)}</dd>
							</div>
							<div>
								<dt class="text-ink-muted">{exitIncidentSecondaryMetricLabel(exitIncident)}</dt>
								<dd class="num">{exitIncidentSecondaryMetricValue(exitIncident)}</dd>
							</div>
						</dl>
						<div class="mt-3 flex flex-wrap items-center gap-2">
							{#if isC4StallWatchdogIncident(exitIncident)}
								<Button
									variant="primary"
									icon={RotateCcw}
									disabled={exitIncidentActionPending || exitIncidentMotionBusy(exitIncident)}
									onclick={() => postExitIncidentAction('auto-resolve')}
								>
									Auto resolve
								</Button>
							{/if}
							<Button
								icon={X}
								disabled={exitIncidentActionPending || exitIncidentMotionBusy(exitIncident)}
								onclick={() => postExitIncidentAction('clear')}
							>
								Incident solved
							</Button>
							{@render incidentDetails(exitIncident, exitIncidentTitle(exitIncident))}
						</div>
						{#if exitIncidentActionError}
							<p class="mt-2 text-danger-ink">{exitIncidentActionError}</p>
						{/if}
					</Alert>
				{/if}

				{#if stallIncident}
					<Alert tone="danger" title="Motor stall" class="shrink-0 max-lg:order-first">
						<div class="flex flex-wrap items-center gap-1.5">
							<Badge>{stallIncidentSteppersLabel(stallIncident)}</Badge>
							<Badge tone="danger">Halted</Badge>
						</div>
						<p class="mt-1.5">
							{#if stallIncident.requires_rehome}
								A stepper stalled and the machine paused. The chute lost its home position, so it
								has to be re-homed before sorting can resume. Clear the jam, then re-home, or clear
								the stall now and re-home later.
							{:else}
								A stepper stalled and the machine paused. Clear the jam, then clear the stall, and
								resume from the header.
							{/if}
						</p>
						{#if incidentString(stallIncident, 'operator_message')}
							<p class="mt-1.5 font-medium">{incidentString(stallIncident, 'operator_message')}</p>
						{/if}
						<div class="mt-3 flex flex-wrap items-center gap-2">
							{#if stallIncident.requires_rehome}
								<Button
									icon={RotateCcw}
									disabled={stallIncidentActionPending}
									onclick={rehomeAfterStall}
								>
									Stall cleared, re-home
								</Button>
								<Button
									variant="ghost"
									icon={Check}
									disabled={stallIncidentActionPending}
									onclick={acknowledgeStallIncident}
								>
									Clear the stall only
								</Button>
							{:else}
								<Button
									icon={Check}
									disabled={stallIncidentActionPending}
									onclick={acknowledgeStallIncident}
								>
									Clear the stall
								</Button>
							{/if}
							{@render incidentDetails(stallIncident, 'Motor stall')}
						</div>
						{#if stallIncidentActionError}
							<p class="mt-2 text-danger-ink">{stallIncidentActionError}</p>
						{/if}
					</Alert>
				{/if}

				{#if needsHomingIncident}
					<Alert tone="danger" title="Needs homing" class="shrink-0 max-lg:order-first">
						<div class="flex flex-wrap items-center gap-1.5">
							<Badge tone="danger">Halted</Badge>
						</div>
						<p class="mt-1.5">
							The chute lost its home position after a stall, so its position can't be trusted.
							Re-home the chute to resume sorting.
						</p>
						{#if incidentString(needsHomingIncident, 'operator_message')}
							<p class="mt-1.5 font-medium">
								{incidentString(needsHomingIncident, 'operator_message')}
							</p>
						{/if}
						<div class="mt-3 flex flex-wrap items-center gap-2">
							<Button icon={RotateCcw} disabled={rehomeIncidentActionPending} onclick={rehomeChute}>
								Re-home the chute
							</Button>
							{@render incidentDetails(needsHomingIncident, 'Needs homing')}
						</div>
						{#if rehomeIncidentActionError}
							<p class="mt-2 text-danger-ink">{rehomeIncidentActionError}</p>
						{/if}
					</Alert>
				{/if}

				<div class="max-lg:order-last lg:contents">
					<CollapsibleSection title="Recent pieces" storageKey="recent" grow>
						<RecentObjects />
					</CollapsibleSection>
				</div>
				<div class="max-lg:order-last lg:contents">
					<CollapsibleSection title="Runtime" storageKey="runtimeTabs">
						<SidebarBottomTabs />
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

<Modal bind:open={incidentDetailsOpen} title={incidentDetailsTitle}>
	{#if incidentDetailsTarget}
		<dl class="divide-y divide-line">
			{#each incidentDetailEntries(incidentDetailsTarget) as entry (entry.key)}
				<div class="flex items-start justify-between gap-4 py-2">
					<dt class="shrink-0 font-mono text-ink-muted">{entry.key}</dt>
					<dd class="max-w-[65%] text-right font-mono break-words text-ink">{entry.value}</dd>
				</div>
			{/each}
		</dl>
	{:else}
		<p class="text-ink-muted">No incident details.</p>
	{/if}
</Modal>
