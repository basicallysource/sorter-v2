<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext, getMachinesContext } from '$lib/machines/context';
	import {
		getBackendHttpBase,
		getBackendWsBase,
		machineHttpBaseUrlFromWsUrl,
		machineWsUrlFromHttpBaseUrl
	} from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import CameraChannelControls from '$lib/components/CameraChannelControls.svelte';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import CollapsibleSection from '$lib/components/CollapsibleSection.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import ResizeHandle from '$lib/components/ResizeHandle.svelte';
	import SidebarBottomTabs from '$lib/components/SidebarBottomTabs.svelte';
	import { buildDashboardFeedCrops, type DashboardFeedCrop } from '$lib/dashboard/crops';
	import { AlertTriangle, Check, Eye, EyeOff, Info, Play, X } from 'lucide-svelte';

	const SIDEBAR_MIN = 300;
	const SIDEBAR_MAX = 900;
	const SIDEBAR_DEFAULT = 420;
	const EXIT_RELEASE_TUNING_STORAGE_KEY = 'sorter:c4-exit-release-tuning:v1';
	const EXIT_STUCK_INCIDENT_KIND = 'exit_stuck';
	const EXIT_RELEASE_DEFAULTS = {
		outputDeg: 1.0,
		speed: 16000,
		acceleration: 40000,
		cycles: 3
	};
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
	let exitIncidentActionPending = $state(false);
	let exitIncidentActionError = $state<string | null>(null);
	let stallIncidentActionPending = $state(false);
	let stallIncidentActionError = $state<string | null>(null);
	let exitReleaseOutputDeg = $state(EXIT_RELEASE_DEFAULTS.outputDeg);
	let exitReleaseSpeed = $state(EXIT_RELEASE_DEFAULTS.speed);
	let exitReleaseAcceleration = $state(EXIT_RELEASE_DEFAULTS.acceleration);
	let exitReleaseCycles = $state(EXIT_RELEASE_DEFAULTS.cycles);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
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
	const noPowerDevelopmentMode = $derived(
		machine.machine?.systemStatus?.no_power_development_mode ?? false
	);
	const startingSystem = $derived(hardwareState === 'homing' || startSystemPending);
	const runtimeStats = $derived((machine.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const exitIncident = $derived(normalizeExitIncident(runtimeStats.active_incident));
	const stallIncident = $derived(stepperStallIncident(runtimeStats.active_incident));

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

	function preferredClassificationCamera(
		hasTop: boolean,
		hasBottom: boolean
	): 'classification_top' | 'classification_bottom' | null {
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

	function stepperStallIncident(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object') return null;
		const incident = value as Record<string, unknown>;
		return incident.kind === 'stepper_stall' ? incident : null;
	}

	function stallIncidentSteppersLabel(incident: Record<string, unknown> | null): string {
		const steppers = incident?.steppers;
		if (Array.isArray(steppers) && steppers.length > 0) {
			return steppers.filter((s) => typeof s === 'string').join(', ');
		}
		return incidentString(incident, 'channel', 'a motor');
	}

	async function acknowledgeStallIncident() {
		if (stallIncidentActionPending) return;
		stallIncidentActionPending = true;
		stallIncidentActionError = null;
		try {
			const response = await fetch(`${currentBackendBaseUrl()}/stall-incident/clear`, {
				method: 'POST'
			});
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			if (!response.ok || payload?.ok === false) {
				throw new Error(
					typeof payload?.detail === 'string' ? payload.detail : 'Could not clear stall'
				);
			}
		} catch (e: any) {
			stallIncidentActionError = e?.message ?? 'Could not clear stall';
		} finally {
			stallIncidentActionPending = false;
		}
	}

	function normalizeExitIncident(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object') return null;
		const incident = value as Record<string, unknown>;
		return incident.kind === 'classification_exit_release' ||
			incident.kind === EXIT_STUCK_INCIDENT_KIND ||
			incident.kind === 'channel_exit_stuck' ||
			incident.kind === 'channel_dropzone_stuck' ||
			incident.kind === 'c2_separation_needed' ||
			incident.kind === 'bulk_feeder_stalled' ||
			incident.kind === 'feeder_detection_unavailable' ||
			incident.kind === 'distribution_chute_jam' ||
			incident.kind === 'distribution_servo_bus_offline' ||
			incident.kind === 'distribution_no_bin_available' ||
			incident.kind === 'classification_unresolved' ||
			incident.kind === 'classification_multi_drop_collision' ||
			incident.kind === 'classification_intake_request_timeout' ||
			incident.kind === 'classification_track_lost' ||
			incident.kind === 'classification_exit_stuck'
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

	function fmtIncidentNumber(value: number | null, suffix = '', digits = 1): string {
		return value === null ? '-' : `${value.toFixed(digits)}${suffix}`;
	}

	function exitIncidentSourceKind(incident: Record<string, unknown> | null): string {
		const sourceKind = incidentString(incident, 'source_kind');
		if (sourceKind) return sourceKind;
		if (incident?.kind === 'classification_exit_release') return 'classification_exit_release';
		if (incident?.kind === 'channel_exit_stuck') return 'channel_exit_stuck';
		if (incident?.kind === EXIT_STUCK_INCIDENT_KIND && incidentString(incident, 'piece_uuid')) {
			return 'classification_exit_release';
		}
		if (incident?.kind === EXIT_STUCK_INCIDENT_KIND && incidentString(incident, 'channel')) {
			return 'channel_exit_stuck';
		}
		return '';
	}

	function isChannelExitStuckIncident(incident: Record<string, unknown> | null): boolean {
		return exitIncidentSourceKind(incident) === 'channel_exit_stuck';
	}

	function isClassificationExitStuckIncident(incident: Record<string, unknown> | null): boolean {
		return exitIncidentSourceKind(incident) === 'classification_exit_release';
	}

	function exitIncidentStatusLabel(incident: Record<string, unknown> | null): string {
		const status = incidentString(incident, 'status', 'waiting_for_operator');
		if (status === 'approved') return 'Queued';
		if (status === 'running' || status === 'auto_release_running') return 'Running';
		if (status === 'manual_test_running') return 'Testing';
		return 'Waiting';
	}

	function exitIncidentMotionBusy(incident: Record<string, unknown> | null): boolean {
		const status = incidentString(incident, 'status');
		return (
			status === 'running' ||
			status === 'auto_release_running' ||
			status === 'approved' ||
			status === 'manual_test_running'
		);
	}

	function exitIncidentCanTestRelease(incident: Record<string, unknown> | null): boolean {
		return isClassificationExitStuckIncident(incident) || isChannelExitStuckIncident(incident);
	}

	function exitIncidentApiBase(incident: Record<string, unknown>): string {
		if (isChannelExitStuckIncident(incident)) {
			return `${currentBackendBaseUrl()}/api/feeder/channel-exit-incident`;
		}
		if (incident.kind === 'channel_dropzone_stuck') {
			return `${currentBackendBaseUrl()}/api/feeder/channel-dropzone-incident`;
		}
		if (incident.kind === 'c2_separation_needed') {
			return `${currentBackendBaseUrl()}/api/feeder/ch2-separation-incident`;
		}
		if (incident.kind === 'bulk_feeder_stalled') {
			return `${currentBackendBaseUrl()}/api/feeder/bulk-feed-incident`;
		}
		if (incident.kind === 'feeder_detection_unavailable') {
			return `${currentBackendBaseUrl()}/api/feeder/detection-incident`;
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
			incident.kind === 'classification_track_lost' ||
			incident.kind === 'classification_exit_stuck'
		) {
			return `${currentBackendBaseUrl()}/api/classification-channel/fallback-incident`;
		}
		return `${currentBackendBaseUrl()}/api/classification-channel/exit-incident`;
	}

	function exitIncidentActionBody(
		incident: Record<string, unknown>
	): Record<string, string | number> {
		if (
			isChannelExitStuckIncident(incident) ||
			incident.kind === 'channel_dropzone_stuck' ||
			incident.kind === 'c2_separation_needed' ||
			incident.kind === 'bulk_feeder_stalled' ||
			incident.kind === 'feeder_detection_unavailable' ||
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
		if (incident?.kind === 'channel_exit_stuck') {
			return 'Exit Stuck';
		}
		if (incident?.kind === 'channel_dropzone_stuck') {
			return 'Dropzone Stuck';
		}
		if (incident?.kind === 'c2_separation_needed') {
			return 'Slip-Stick Separation';
		}
		if (incident?.kind === 'bulk_feeder_stalled') {
			return 'Bulk Feed Stalled';
		}
		if (incident?.kind === 'feeder_detection_unavailable') {
			return 'Detection Unavailable';
		}
		if (incident?.kind === 'distribution_chute_jam') {
			return 'Chute Jam';
		}
		if (incident?.kind === 'distribution_servo_bus_offline') {
			return 'Servo Bus Offline';
		}
		if (incident?.kind === 'distribution_no_bin_available') {
			return 'No Bin Available';
		}
		if (incident?.kind === 'classification_unresolved') {
			return 'Classification Unresolved';
		}
		if (incident?.kind === 'classification_multi_drop_collision') {
			return 'Multi-Drop Collision';
		}
		if (incident?.kind === 'classification_intake_request_timeout') {
			return 'Intake Request Timeout';
		}
		if (incident?.kind === 'classification_track_lost') {
			return 'Track Lost';
		}
		if (incident?.kind === 'classification_exit_stuck') {
			return 'C4 Piece Stuck';
		}
		return 'Exit Stuck';
	}

	function exitIncidentScopeLabel(incident: Record<string, unknown> | null): string {
		const role = incidentString(incident, 'role');
		const channel = incidentString(incident, 'channel');
		if (role === 'c_channel_2' || channel === 'c2') return 'C2';
		if (role === 'c_channel_3' || channel === 'c3') return 'C3';
		if (role === 'bulk_feeder' || channel === 'c1') return 'C1';
		if (role === 'feeder_detection' || channel === 'feeder') return 'Feeder';
		if (channel === 'distribution' || role.startsWith('distribution_')) return 'Distribution';
		if (isClassificationExitStuckIncident(incident) || role === 'carousel' || channel === 'c4')
			return 'C4';
		return '';
	}

	function exitIncidentDescription(incident: Record<string, unknown> | null): string {
		if (isChannelExitStuckIncident(incident) || isClassificationExitStuckIncident(incident)) {
			return 'A piece is not falling off the channel.';
		}
		if (incident?.kind === 'channel_dropzone_stuck') {
			return 'A piece is not moving as expected.';
		}
		if (incident?.kind === 'c2_separation_needed') {
			return 'Pieces are not spreading out as expected.';
		}
		if (incident?.kind === 'bulk_feeder_stalled') {
			return 'No pieces are reaching the next channel.';
		}
		if (incident?.kind === 'feeder_detection_unavailable') {
			return 'Feeder camera detection is not reliable.';
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
		if (incident?.kind === 'classification_exit_stuck') {
			return 'A piece is stuck on the classification channel and could not be discharged. Remove it from the channel, then resolve to resume feeding.';
		}
		return 'A piece is not falling off the channel.';
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
		if (incident?.kind === 'c2_separation_needed') return 'Tracks';
		if (incident?.kind === 'bulk_feeder_stalled') return 'Stall';
		if (incident?.kind === 'feeder_detection_unavailable') return 'Unavailable';
		if (incident?.kind === 'distribution_chute_jam') return 'Elapsed';
		if (incident?.kind === 'distribution_servo_bus_offline') return 'Offline';
		if (incident?.kind === 'channel_dropzone_stuck') return 'Motion';
		return isChannelExitStuckIncident(incident) ? 'Stall' : 'Offset';
	}

	function exitIncidentPrimaryMetricValue(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'c2_separation_needed') {
			const detections = incidentNumber(incident, 'detection_count');
			return detections === null ? '-' : detections.toFixed(0);
		}
		if (isChannelExitStuckIncident(incident)) {
			const stall = incidentNumber(incident, 'stall_ms');
			return stall === null ? '-' : `${stall.toFixed(0)} ms`;
		}
		if (incident?.kind === 'channel_dropzone_stuck') {
			const motion =
				incidentNumber(incident, 'accumulated_motion_ms') ?? incidentNumber(incident, 'stall_ms');
			return motion === null ? '-' : `${motion.toFixed(0)} ms`;
		}
		if (incident?.kind === 'bulk_feeder_stalled') {
			const stalled = incidentNumber(incident, 'stalled_ms');
			return stalled === null ? '-' : `${stalled.toFixed(0)} ms`;
		}
		if (incident?.kind === 'feeder_detection_unavailable') {
			const unavailable = incidentNumber(incident, 'unavailable_ms');
			return unavailable === null ? '-' : `${unavailable.toFixed(0)} ms`;
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
		return fmtIncidentNumber(incidentNumber(incident, 'center_offset_deg'), ' deg');
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
		if (incident?.kind === 'bulk_feeder_stalled') return 'Pulses';
		if (incident?.kind === 'feeder_detection_unavailable') return 'Detail';
		if (
			incident?.kind === 'distribution_chute_jam' ||
			incident?.kind === 'distribution_servo_bus_offline'
		)
			return 'Detail';
		return incident?.kind === 'c2_separation_needed' ? 'Motion' : 'Overlap';
	}

	function exitIncidentSecondaryMetricValue(incident: Record<string, unknown> | null): string {
		if (incident?.kind === 'c2_separation_needed') {
			return incident.automated_motion_enabled === true ? 'Enabled' : 'Disabled';
		}
		if (incident?.kind === 'bulk_feeder_stalled') {
			const pulses = incidentNumber(incident, 'pulses_since_activity');
			const minPulses = incidentNumber(incident, 'min_pulses');
			if (pulses === null) return '-';
			return minPulses === null ? pulses.toFixed(0) : `${pulses.toFixed(0)} / ${minPulses.toFixed(0)}`;
		}
		if (incident?.kind === 'feeder_detection_unavailable') {
			return incidentString(incident, 'detail', '-');
		}
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
		return fmtIncidentNumber((incidentNumber(incident, 'overlap_ratio') ?? 0) * 100, '%', 0);
	}

	function exitIncidentStageLabel(incident: Record<string, unknown> | null): string {
		const stageNumber = incidentNumber(incident, 'stage_number');
		const stageCount = incidentNumber(incident, 'stage_count');
		const stageName = incidentString(incident, 'stage_name', 'release');
		if (stageNumber !== null && stageCount !== null) {
			return `${stageNumber.toFixed(0)}/${stageCount.toFixed(0)} ${stageName}`;
		}
		return stageName;
	}

	function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
		const parsed = typeof value === 'number' ? value : Number(value);
		if (!Number.isFinite(parsed)) return fallback;
		return Math.min(max, Math.max(min, parsed));
	}

	function readExitReleaseTuning() {
		try {
			const raw = window.localStorage.getItem(EXIT_RELEASE_TUNING_STORAGE_KEY);
			if (!raw) return null;
			const parsed = JSON.parse(raw) as Record<string, unknown>;
			return {
				outputDeg: clampNumber(
					parsed.outputDeg ?? parsed.amplitude_output_deg,
					EXIT_RELEASE_DEFAULTS.outputDeg,
					0.1,
					12
				),
				speed: clampNumber(
					parsed.speed ?? parsed.microsteps_per_second,
					EXIT_RELEASE_DEFAULTS.speed,
					100,
					16000
				),
				acceleration: Math.round(
					clampNumber(
						parsed.acceleration ?? parsed.acceleration_microsteps_per_second_sq,
						EXIT_RELEASE_DEFAULTS.acceleration,
						1000,
						48000
					)
				),
				cycles: Math.round(clampNumber(parsed.cycles, EXIT_RELEASE_DEFAULTS.cycles, 1, 20))
			};
		} catch {
			return null;
		}
	}

	function writeExitReleaseTuning() {
		try {
			window.localStorage.setItem(
				EXIT_RELEASE_TUNING_STORAGE_KEY,
				JSON.stringify({
					outputDeg: exitReleaseOutputDeg,
					speed: Math.round(exitReleaseSpeed),
					acceleration: Math.round(exitReleaseAcceleration),
					cycles: Math.round(exitReleaseCycles)
				})
			);
		} catch {
			// Local storage is a convenience only; slider control must keep working.
		}
	}

	function setExitReleaseOutputDeg(value: number) {
		exitReleaseOutputDeg = clampNumber(value, EXIT_RELEASE_DEFAULTS.outputDeg, 0.1, 12);
		writeExitReleaseTuning();
	}

	function setExitReleaseSpeed(value: number) {
		exitReleaseSpeed = Math.round(clampNumber(value, EXIT_RELEASE_DEFAULTS.speed, 100, 16000));
		writeExitReleaseTuning();
	}

	function setExitReleaseAcceleration(value: number) {
		exitReleaseAcceleration = Math.round(
			clampNumber(value, EXIT_RELEASE_DEFAULTS.acceleration, 1000, 48000)
		);
		writeExitReleaseTuning();
	}

	function setExitReleaseCycles(value: number) {
		exitReleaseCycles = Math.round(clampNumber(value, EXIT_RELEASE_DEFAULTS.cycles, 1, 20));
		writeExitReleaseTuning();
	}

	async function postExitIncidentAction(action: 'continue' | 'acknowledge' | 'clear') {
		const incident = exitIncident;
		if (!incident || exitIncidentActionPending) return;
		if (
			incident.kind === 'channel_dropzone_stuck' &&
			action !== 'acknowledge' &&
			action !== 'clear'
		)
			return;
		if (
			(isChannelExitStuckIncident(incident) ||
				incident.kind === 'c2_separation_needed' ||
				incident.kind === 'bulk_feeder_stalled' ||
				incident.kind === 'feeder_detection_unavailable' ||
				incident.kind === 'distribution_chute_jam' ||
				incident.kind === 'distribution_servo_bus_offline') &&
			action !== 'clear'
		)
			return;
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

	async function postExitIncidentTestRelease() {
		const incident = exitIncident;
		if (
			!incident ||
			!exitIncidentCanTestRelease(incident) ||
			exitIncidentActionPending ||
			exitIncidentMotionBusy(incident)
		)
			return;
		exitIncidentActionPending = true;
		exitIncidentActionError = null;
		try {
			const response = await fetch(`${exitIncidentApiBase(incident)}/test-release`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					...exitIncidentActionBody(incident),
					amplitude_output_deg: exitReleaseOutputDeg,
					microsteps_per_second: Math.round(exitReleaseSpeed),
					acceleration_microsteps_per_second_sq: Math.round(exitReleaseAcceleration),
					cycles: Math.round(exitReleaseCycles)
				})
			});
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			if (!response.ok || payload?.ok === false) {
				const detail = payload?.detail;
				throw new Error(typeof detail === 'string' ? detail : 'Could not run exit release test');
			}
		} catch (e: any) {
			exitIncidentActionError = e?.message ?? 'Could not run exit release test';
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
		const savedExitReleaseTuning = readExitReleaseTuning();
		if (savedExitReleaseTuning) {
			exitReleaseOutputDeg = savedExitReleaseTuning.outputDeg;
			exitReleaseSpeed = savedExitReleaseTuning.speed;
			exitReleaseAcceleration = savedExitReleaseTuning.acceleration;
			exitReleaseCycles = savedExitReleaseTuning.cycles;
		}
		if (machine.machine) {
			const baseUrl = currentBackendBaseUrl();
			void fetchDashboardCrops(baseUrl);
			void loadMachineSetup(baseUrl);
		}
	});
</script>

<svelte:head><title>Sorter - Dashboard</title></svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-6">
		{#if machine.machine}
			<div class="flex h-[calc(100vh-7rem)] min-h-0 gap-3">
				{#if camera_layout === 'split_feeder'}
					{@const uses_chamber = machineSetup !== 'classification_channel'}
					{@const has_cls_top = uses_chamber && isConfigured('classification_top')}
					{@const has_cls_bottom = uses_chamber && isConfigured('classification_bottom')}
					{@const classification_camera = preferredClassificationCamera(
						has_cls_top,
						has_cls_bottom
					)}
					<div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
						<div class="flex min-h-0 flex-1 gap-3">
							<div class="min-w-0 flex-1">
								<CameraFeed
									camera="c_channel_2"
									label={cameraLabel('c_channel_2')}
									crop={cropFor('c_channel_2')}
									controls={['annotations', 'zones', 'crop', 'fullscreen']}
								>
									{#snippet headerActions()}
										<CameraChannelControls stepperKey="c_channel_2" />
									{/snippet}
								</CameraFeed>
							</div>
							<div class="min-w-0 flex-1">
								<CameraFeed
									camera="c_channel_3"
									label={cameraLabel('c_channel_3')}
									crop={cropFor('c_channel_3')}
									controls={['annotations', 'zones', 'crop', 'fullscreen']}
								>
									{#snippet headerActions()}
										<CameraChannelControls stepperKey="c_channel_3" />
									{/snippet}
								</CameraFeed>
							</div>
						</div>
						<div class="flex min-h-0 flex-1 gap-3">
							<div class="min-w-0 flex-1">
								<CameraFeed
									camera={c4CameraRole}
									label={cameraLabel(c4CameraRole)}
									crop={cropFor(c4CameraRole)}
									controls={['annotations', 'zones', 'crop', 'fullscreen']}
								>
									{#snippet headerActions()}
										<CameraChannelControls stepperKey="c_channel_4" />
									{/snippet}
								</CameraFeed>
							</div>
							{#if classification_camera}
								<div class="min-w-0 flex-1">
									<div class="setup-card-shell flex h-full min-h-0 flex-col border">
										<div
											class="setup-card-header flex items-center justify-between px-3 py-2 text-sm"
										>
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
													onclick={() =>
														(classification_layer =
															classification_layer === 'annotated' ? 'raw' : 'annotated')}
													class="p-1 text-text transition-colors hover:bg-white/70"
													title={classification_layer === 'annotated'
														? 'Show raw'
														: 'Show annotations'}
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
					{#if classification_camera && (has_top ? 1 : 0) + (has_bottom ? 1 : 0) === 1}
						<div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
							<div class="min-w-0 flex-1">
								<CameraFeed
									camera="feeder"
									label={cameraLabel('feeder')}
									crop={cropFor('feeder')}
									controls={['annotations', 'zones', 'crop', 'fullscreen']}
								/>
							</div>
							<div class="min-w-0 flex-1">
								<CameraFeed
									camera={classification_camera}
									label={cameraLabel(classification_camera)}
									crop={cropFor(classification_camera)}
									controls={['annotations', 'crop', 'fullscreen']}
								/>
							</div>
						</div>
					{:else}
						<div class="flex min-h-0 min-w-0 flex-1 gap-3">
							<div class="min-w-0 flex-1">
								<CameraFeed
									camera="feeder"
									label={cameraLabel('feeder')}
									crop={cropFor('feeder')}
									controls={['annotations', 'zones', 'crop', 'fullscreen']}
								/>
							</div>
							{#if classification_camera}
								<div class="setup-card-shell flex min-h-0 flex-1 flex-col border">
									<div
										class="setup-card-header flex items-center justify-between px-3 py-2 text-sm"
									>
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
												onclick={() =>
													(classification_layer =
														classification_layer === 'annotated' ? 'raw' : 'annotated')}
												class="p-1 text-text transition-colors hover:bg-white/70"
												title={classification_layer === 'annotated'
													? 'Show raw'
													: 'Show annotations'}
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

				<div
					class="flex min-h-0 flex-shrink-0 flex-col gap-3 overflow-y-auto"
					style="width: {sidebar_width}px;"
				>
					{#if hardwareState !== 'ready'}
						<div class="shrink-0 border border-border bg-bg px-4 py-3">
							{#if hardwareState === 'standby'}
								<div class="flex items-center justify-between gap-3">
									<div>
										<div class="text-sm font-medium text-text">System Standby</div>
										<div class="text-xs text-text-muted">
											{#if noPowerDevelopmentMode}
												Sim Home runs the normal recovery path and skips only the physical homing steps.
											{:else}
												Press Home to initialize hardware and home all axes.
											{/if}
										</div>
										{#if startSystemError}
											<div class="mt-1 text-xs text-danger">{startSystemError}</div>
										{/if}
									</div>
									<div class="flex shrink-0 items-center gap-2">
										{#if noPowerDevelopmentMode}
											<button
												onclick={startSystem}
												disabled={startingSystem}
												class="cursor-pointer border border-border bg-surface px-4 py-1.5 text-sm font-medium text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50"
											>
												Sim Home
											</button>
										{/if}
										<button
											onclick={startSystem}
											disabled={startingSystem}
											class="cursor-pointer border border-success bg-success px-4 py-1.5 text-sm font-medium text-white hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-50"
										>
											Home
										</button>
									</div>
								</div>
							{:else if hardwareState === 'homing'}
								<div class="flex items-center gap-3">
									<div
										class="h-4 w-4 animate-spin border-2 border-primary border-t-transparent"
										style="border-radius: 50%;"
									></div>
									<div>
										<div class="text-sm font-medium text-text">Homing...</div>
										<div class="text-xs text-text-muted">
											{homingStep ?? 'Initializing hardware...'}
										</div>
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
					{#if exitIncident}
						<div class="shrink-0 border border-warning/50 bg-warning/10 px-4 py-3">
							<div class="flex items-start justify-between gap-3">
								<div class="flex min-w-0 items-start gap-2">
									<AlertTriangle size={17} class="mt-0.5 shrink-0 text-warning-dark" />
									<div class="min-w-0">
										<div class="flex flex-wrap items-center gap-2">
											<div class="text-sm font-semibold text-text">
												{exitIncidentTitle(exitIncident)}
											</div>
											{#if exitIncidentScopeLabel(exitIncident)}
												<div class="bg-bg/70 px-1.5 py-0.5 text-[10px] text-text-muted">
													{exitIncidentScopeLabel(exitIncident)}
												</div>
											{/if}
											<div
												class="bg-warning px-1.5 py-0.5 text-[10px] font-semibold text-warning-dark uppercase"
											>
												{exitIncidentStatusLabel(exitIncident)}
											</div>
										</div>
										<div class="mt-1 text-xs text-text-muted">
											{exitIncidentDescription(exitIncident)}
										</div>
										{#if incidentString(exitIncident, 'operator_message')}
											<div class="mt-2 bg-warning/10 px-2 py-1.5 text-xs text-warning-dark">
												{incidentString(exitIncident, 'operator_message')}
											</div>
										{/if}
									</div>
								</div>
							</div>
							{#if exitIncident?.kind !== 'classification_exit_stuck'}
							<div class="mt-3 grid grid-cols-2 gap-2 text-xs">
								<div class="bg-bg/70 px-2 py-1.5">
									<div class="text-text-muted">
										{exitIncidentPrimaryMetricLabel(exitIncident)}
									</div>
									<div class="font-mono text-text tabular-nums">
										{exitIncidentPrimaryMetricValue(exitIncident)}
									</div>
								</div>
								<div class="bg-bg/70 px-2 py-1.5">
									<div class="text-text-muted">
										{exitIncidentSecondaryMetricLabel(exitIncident)}
									</div>
									<div class="font-mono text-text tabular-nums">
										{exitIncidentSecondaryMetricValue(exitIncident)}
									</div>
								</div>
								{#if exitIncidentCanTestRelease(exitIncident)}
									<div class="col-span-2 bg-bg/70 px-2 py-1.5">
										<div class="text-text-muted">Suggested Release</div>
										<div class="text-text">{exitIncidentStageLabel(exitIncident)}</div>
										<div class="mt-0.5 font-mono text-[11px] text-text-muted tabular-nums">
											{fmtIncidentNumber(
												incidentNumber(exitIncident, 'amplitude_output_deg'),
												' deg'
											)} / {incidentNumber(exitIncident, 'cycles')?.toFixed(0) ?? '-'} cycles / {incidentNumber(
												exitIncident,
												'microsteps_per_second'
											)?.toFixed(0) ?? '-'} usteps/s / {incidentNumber(
												exitIncident,
												'acceleration_microsteps_per_second_sq'
											)?.toFixed(0) ?? '-'} usteps/s2
										</div>
									</div>
								{/if}
							</div>
							{/if}
							{#if exitIncidentCanTestRelease(exitIncident)}
								<div class="mt-3 bg-bg/70 px-3 py-2">
									<div class="flex items-center justify-between gap-3">
										<label for="exit-release-deg" class="text-xs font-medium text-text"
											>Test swing</label
										>
										<span class="font-mono text-xs text-text tabular-nums"
											>{exitReleaseOutputDeg.toFixed(1)} deg</span
										>
									</div>
									<input
										id="exit-release-deg"
										type="range"
										min="0.1"
										max="12"
										step="0.1"
										value={exitReleaseOutputDeg}
										oninput={(event) =>
											setExitReleaseOutputDeg(
												Number((event.currentTarget as HTMLInputElement).value)
											)}
										class="mt-2 w-full accent-warning"
									/>
									<div class="mt-3 flex items-center justify-between gap-3">
										<label for="exit-release-speed" class="text-xs font-medium text-text"
											>Test speed</label
										>
										<span class="font-mono text-xs text-text tabular-nums"
											>{Math.round(exitReleaseSpeed)} usteps/s</span
										>
									</div>
									<input
										id="exit-release-speed"
										type="range"
										min="100"
										max="16000"
										step="100"
										value={exitReleaseSpeed}
										oninput={(event) =>
											setExitReleaseSpeed(Number((event.currentTarget as HTMLInputElement).value))}
										class="mt-2 w-full accent-warning"
									/>
									<div class="mt-3 flex items-center justify-between gap-3">
										<label for="exit-release-acceleration" class="text-xs font-medium text-text"
											>Acceleration</label
										>
										<span class="font-mono text-xs text-text tabular-nums"
											>{Math.round(exitReleaseAcceleration)} usteps/s2</span
										>
									</div>
									<input
										id="exit-release-acceleration"
										type="range"
										min="1000"
										max="48000"
										step="500"
										value={exitReleaseAcceleration}
										oninput={(event) =>
											setExitReleaseAcceleration(
												Number((event.currentTarget as HTMLInputElement).value)
											)}
										class="mt-2 w-full accent-warning"
									/>
									<div class="mt-3 flex items-center justify-between gap-3">
										<label for="exit-release-cycles" class="text-xs font-medium text-text"
											>Repeats</label
										>
										<span class="font-mono text-xs text-text tabular-nums"
											>{Math.round(exitReleaseCycles)}x</span
										>
									</div>
									<input
										id="exit-release-cycles"
										type="range"
										min="1"
										max="20"
										step="1"
										value={exitReleaseCycles}
										oninput={(event) =>
											setExitReleaseCycles(Number((event.currentTarget as HTMLInputElement).value))}
										class="mt-2 w-full accent-warning"
									/>
								</div>
							{/if}
							<div class="mt-3 flex flex-wrap gap-2">
								{#if exitIncidentCanTestRelease(exitIncident)}
									<button
										type="button"
										onclick={postExitIncidentTestRelease}
										disabled={exitIncidentActionPending || exitIncidentMotionBusy(exitIncident)}
										class="inline-flex min-h-10 items-center gap-1.5 bg-warning px-3 py-1.5 text-xs font-semibold text-warning-dark transition-transform hover:bg-warning/90 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50"
									>
										<Play size={13} />
										Test Wiggle
									</button>
								{/if}
								{#if exitIncident.kind === 'channel_dropzone_stuck'}
									<button
										type="button"
										onclick={() => postExitIncidentAction('acknowledge')}
										disabled={exitIncidentActionPending}
										class="inline-flex min-h-10 items-center gap-1.5 bg-warning px-3 py-1.5 text-xs font-semibold text-warning-dark transition-transform hover:bg-warning/90 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50"
									>
										<Check size={13} />
										Ignore Until Clear
									</button>
								{/if}
								<button
									type="button"
									onclick={() => postExitIncidentAction('clear')}
									disabled={exitIncidentActionPending || exitIncidentMotionBusy(exitIncident)}
									class="inline-flex min-h-10 items-center gap-1.5 bg-bg px-3 py-1.5 text-xs font-medium text-text shadow-[inset_0_0_0_1px_var(--color-border)] transition-transform hover:bg-surface active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50"
								>
									<X size={13} />
									Incident Solved
								</button>
								<button
									type="button"
									onclick={() => openIncidentDetails(exitIncident, exitIncidentTitle(exitIncident))}
									title="Incident details"
									class="ml-auto inline-flex min-h-10 items-center gap-1.5 px-2 py-1.5 text-xs font-medium text-text-muted transition-colors hover:bg-bg/70 hover:text-text"
								>
									<Info size={14} />
									Details
								</button>
							</div>
							{#if exitIncidentActionError}
								<div class="mt-2 text-xs text-danger">{exitIncidentActionError}</div>
							{/if}
						</div>
					{/if}
					{#if stallIncident}
						<div class="shrink-0 border border-danger/50 bg-danger/10 px-4 py-3">
							<div class="flex items-start justify-between gap-3">
								<div class="flex min-w-0 items-start gap-2">
									<AlertTriangle size={17} class="mt-0.5 shrink-0 text-danger" />
									<div class="min-w-0">
										<div class="flex flex-wrap items-center gap-2">
											<div class="text-sm font-semibold text-text">Motor Stall</div>
											<div class="bg-bg/70 px-1.5 py-0.5 text-[10px] text-text-muted">
												{stallIncidentSteppersLabel(stallIncident)}
											</div>
											<div
												class="bg-danger px-1.5 py-0.5 text-[10px] font-semibold text-white uppercase"
											>
												Halted
											</div>
										</div>
										<div class="mt-1 text-xs text-text-muted">
											A stepper stalled and the machine has stopped. Clear the jam, then
											acknowledge to re-arm detection and resume.
										</div>
										{#if incidentString(stallIncident, 'operator_message')}
											<div class="mt-2 bg-danger/10 px-2 py-1.5 text-xs text-danger">
												{incidentString(stallIncident, 'operator_message')}
											</div>
										{/if}
									</div>
								</div>
							</div>
							<div class="mt-3 flex flex-wrap items-center gap-2">
								<button
									type="button"
									onclick={acknowledgeStallIncident}
									disabled={stallIncidentActionPending}
									class="inline-flex min-h-10 items-center gap-1.5 bg-bg px-3 py-1.5 text-xs font-medium text-text shadow-[inset_0_0_0_1px_var(--color-border)] transition-transform hover:bg-surface active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50"
								>
									<Check size={13} />
									Stall Cleared — Resume
								</button>
								<button
									type="button"
									onclick={() => openIncidentDetails(stallIncident, 'Motor Stall')}
									title="Incident details"
									class="ml-auto inline-flex min-h-10 items-center gap-1.5 px-2 py-1.5 text-xs font-medium text-text-muted transition-colors hover:bg-bg/70 hover:text-text"
								>
									<Info size={14} />
									Details
								</button>
							</div>
							{#if stallIncidentActionError}
								<div class="mt-2 text-xs text-danger">{stallIncidentActionError}</div>
							{/if}
						</div>
					{/if}
					<CollapsibleSection title="Recent Pieces" storageKey="recent" grow>
						<RecentObjects />
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
<Modal bind:open={incidentDetailsOpen} title={incidentDetailsTitle}>
	{#if incidentDetailsTarget}
		<dl class="flex flex-col divide-y divide-border/40">
			{#each incidentDetailEntries(incidentDetailsTarget) as entry (entry.key)}
				<div class="flex items-start justify-between gap-4 py-1.5">
					<dt class="shrink-0 font-mono text-xs text-text-muted">{entry.key}</dt>
					<dd class="max-w-[65%] break-words text-right font-mono text-sm text-text">
						{entry.value}
					</dd>
				</div>
			{/each}
		</dl>
	{:else}
		<div class="text-sm text-text-muted">No incident details available.</div>
	{/if}
</Modal>
