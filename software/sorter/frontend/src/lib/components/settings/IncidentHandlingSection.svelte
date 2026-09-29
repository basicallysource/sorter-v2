<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';

	const EXIT_STUCK_INCIDENT_KIND = 'exit_stuck';

	type IncidentHandlingMode = 'off' | 'manual' | 'automatic';
	type IncidentDefinition = {
		kind: string;
		label: string;
		scope: string;
		description: string;
		off_label: string;
		manual_label: string;
		automatic_label: string;
		automatic_supported: boolean;
	};

	const INCIDENT_FALLBACK_DEFINITIONS: IncidentDefinition[] = [
		{
			kind: EXIT_STUCK_INCIDENT_KIND,
			label: 'Exit Stuck',
			scope: 'C4',
			description: 'The classification channel stopped making progress with a piece on it.',
			off_label: 'Do not raise exit-stuck incidents',
			manual_label: 'Operator clears the stuck piece',
			automatic_label: 'Rotate the channel forward until it clears',
			automatic_supported: true
		},
		{
			kind: 'feeder_jam',
			label: 'Feeder Jam',
			scope: 'Feeder',
			description:
				"A feeder channel keeps trying to advance a piece that will not move — it is hung at the previous channel's hand-off.",
			off_label: 'Do not detect feeder hand-off jams',
			manual_label: 'Call the operator as soon as a channel is stuck',
			automatic_label: 'Nudge the upstream channel to free it, then call the operator',
			automatic_supported: true
		},
		{
			kind: 'distribution_chute_jam',
			label: 'Chute Jam',
			scope: 'Distribution',
			description: 'The distribution chute did not finish moving.',
			off_label: 'Use hardware alert only',
			manual_label: 'Operator clears the chute',
			automatic_label: 'Automatic chute recovery',
			automatic_supported: false
		},
		{
			kind: 'distribution_servo_bus_offline',
			label: 'Servo Bus Offline',
			scope: 'Distribution',
			description: 'The distribution servo bus is not responding.',
			off_label: 'Use hardware alert only',
			manual_label: 'Operator restores the servo bus',
			automatic_label: 'Automatic servo bus recovery',
			automatic_supported: false
		},
		{
			kind: 'distribution_no_bin_available',
			label: 'No Bin Available',
			scope: 'Distribution',
			description: 'No matching bin is available for the piece.',
			off_label: 'Allow bottom-tray passthrough',
			manual_label: 'Operator assigns capacity or approves passthrough',
			automatic_label: 'Automatic no-bin passthrough',
			automatic_supported: false
		}
	];

	const machine = getMachineContext();

	let incidentDefinitions = $state<IncidentDefinition[]>(INCIDENT_FALLBACK_DEFINITIONS);
	let incidentHandling = $state<Record<string, IncidentHandlingMode>>({});
	let incidentPolicySaving = $state<string | null>(null);
	let incidentPolicyError = $state<string | null>(null);
	let configBaseUrl = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function normalizeIncidentMode(value: unknown): IncidentHandlingMode {
		if (value === 'automatic') return 'automatic';
		if (value === 'off') return 'off';
		return 'manual';
	}

	function normalizeIncidentDefinitions(value: unknown): IncidentDefinition[] {
		if (!Array.isArray(value)) return INCIDENT_FALLBACK_DEFINITIONS;
		const normalized = value
			.map((entry) => {
				if (!entry || typeof entry !== 'object') return null;
				const raw = entry as Record<string, unknown>;
				if (typeof raw.kind !== 'string' || typeof raw.label !== 'string') return null;
				return {
					kind: raw.kind,
					label: raw.label,
					scope: typeof raw.scope === 'string' ? raw.scope : '',
					description:
						typeof raw.description === 'string' ? raw.description : 'Operator review required.',
					off_label: typeof raw.off_label === 'string' ? raw.off_label : 'Disabled',
					manual_label:
						typeof raw.manual_label === 'string' ? raw.manual_label : 'Operator reviews',
					automatic_label:
						typeof raw.automatic_label === 'string' ? raw.automatic_label : 'Automatic',
					automatic_supported: raw.automatic_supported === true
				} satisfies IncidentDefinition;
			})
			.filter((entry): entry is IncidentDefinition => entry !== null);
		const seen = new Set<string>();
		const deduped = normalized.filter((entry) => {
			if (seen.has(entry.kind)) return false;
			seen.add(entry.kind);
			return true;
		});
		return deduped.length > 0 ? deduped : INCIDENT_FALLBACK_DEFINITIONS;
	}

	function incidentMode(kind: string): IncidentHandlingMode {
		return normalizeIncidentMode(incidentHandling[kind]);
	}

	const runtimeStats = $derived((machine.machine?.runtimeStats ?? {}) as Record<string, unknown>);
	const activeIncidentKind = $derived.by(() => {
		const incident = runtimeStats.active_incident;
		if (!incident || typeof incident !== 'object') return null;
		const kind = (incident as Record<string, unknown>).kind;
		return typeof kind === 'string' && kind.length > 0 ? kind : null;
	});

	function incidentDefinitionActive(definition: IncidentDefinition): boolean {
		return activeIncidentKind === definition.kind;
	}

	function incidentModeButtonClass(active: boolean, disabled = false): string {
		const base =
			'min-h-8 px-2.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40';
		if (active)
			return `${base} bg-primary text-white`;
		if (disabled)
			return `${base} bg-well text-ink-muted`;
		return `${base} bg-well text-ink-muted hover:bg-surface hover:text-ink`;
	}

	async function saveIncidentMode(kind: string, mode: IncidentHandlingMode) {
		if (incidentPolicySaving) return;
		const previous = incidentMode(kind);
		if (previous === mode) return;
		incidentPolicySaving = kind;
		incidentPolicyError = null;
		incidentHandling = { ...incidentHandling, [kind]: mode };
		try {
			const response = await fetch(`${currentBackendBaseUrl()}/api/system/dashboard-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ incident_handling: { [kind]: mode } })
			});
			const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
			if (!response.ok || payload?.ok === false) {
				throw new Error(
					typeof payload?.detail === 'string' ? payload.detail : 'Could not save incident mode'
				);
			}
			const handling = payload?.incident_handling;
			if (handling && typeof handling === 'object') {
				const next: Record<string, IncidentHandlingMode> = {};
				for (const definition of incidentDefinitions) {
					next[definition.kind] = normalizeIncidentMode(
						(handling as Record<string, unknown>)[definition.kind]
					);
				}
				incidentHandling = next;
			}
		} catch (e: any) {
			incidentHandling = { ...incidentHandling, [kind]: previous };
			incidentPolicyError = e?.message ?? 'Could not save incident mode';
		} finally {
			incidentPolicySaving = null;
		}
	}

	async function loadDashboardConfig(base_url: string) {
		try {
			const res = await fetch(`${base_url}/api/system/dashboard-config`);
			if (!res.ok) return;
			const payload = await res.json();
			const definitions = normalizeIncidentDefinitions(payload?.incident_definitions);
			incidentDefinitions = definitions;
			const handling =
				payload?.incident_handling && typeof payload.incident_handling === 'object'
					? (payload.incident_handling as Record<string, unknown>)
					: {};
			const nextHandling: Record<string, IncidentHandlingMode> = {};
			for (const definition of definitions) {
				nextHandling[definition.kind] = normalizeIncidentMode(handling[definition.kind]);
			}
			incidentHandling = nextHandling;
		} catch {
			// ignore transient shell fetch issues
		}
	}

	$effect(() => {
		if (!machine.machine) {
			configBaseUrl = null;
			return;
		}
		const base_url = currentBackendBaseUrl();
		if (configBaseUrl === base_url) return;
		configBaseUrl = base_url;
		void loadDashboardConfig(base_url);
	});

	onMount(() => {
		if (machine.machine) {
			void loadDashboardConfig(currentBackendBaseUrl());
		}
	});
</script>

<div class="flex flex-col gap-2">
	{#each incidentDefinitions as definition (definition.kind)}
		{@const mode = incidentMode(definition.kind)}
		{@const active = incidentDefinitionActive(definition)}
		<div class="border border-line bg-well px-3 py-2">
			<div class="flex items-start justify-between gap-3">
				<div class="min-w-0">
					<div class="flex flex-wrap items-center gap-2">
						<div class="text-sm font-semibold text-ink">{definition.label}</div>
						{#if definition.scope}
							<div class="bg-surface px-1.5 py-0.5 text-xs text-ink-muted">
								{definition.scope}
							</div>
						{/if}
						{#if active}
							<div
								class="bg-warning px-1.5 py-0.5 text-xs font-semibold text-warning-ink"
							>
								Active
							</div>
						{/if}
					</div>
					<div class="mt-1 text-sm text-ink-muted">{definition.description}</div>
				</div>
				<div class="flex shrink-0 overflow-hidden">
					<button
						type="button"
						onclick={() => void saveIncidentMode(definition.kind, 'off')}
						disabled={incidentPolicySaving === definition.kind}
						class={incidentModeButtonClass(mode === 'off')}
					>
						Off
					</button>
					<button
						type="button"
						onclick={() => void saveIncidentMode(definition.kind, 'manual')}
						disabled={incidentPolicySaving === definition.kind}
						class={incidentModeButtonClass(mode === 'manual')}
					>
						Manual
					</button>
					<button
						type="button"
						onclick={() => void saveIncidentMode(definition.kind, 'automatic')}
						disabled={!definition.automatic_supported ||
							incidentPolicySaving === definition.kind}
						class={incidentModeButtonClass(
							mode === 'automatic',
							!definition.automatic_supported
						)}
						title={definition.automatic_supported ? definition.automatic_label : 'Manual only'}
					>
						Auto
					</button>
				</div>
			</div>
		</div>
	{/each}
	{#if incidentPolicyError}
		<div class="text-sm text-danger-ink">{incidentPolicyError}</div>
	{/if}
</div>
