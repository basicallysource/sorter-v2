<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';

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
		default: IncidentHandlingMode;
	};

	const MODE_NAMES: Record<IncidentHandlingMode, string> = {
		off: 'Off',
		manual: 'Manual',
		automatic: 'Automatic'
	};

	const machine = getMachineContext();

	let incidentDefinitions = $state<IncidentDefinition[]>([]);
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

	// The backend names its incidents in Title Case; the UI writes sentence case.
	const sentenceCase = (text: string) =>
		text.replace(/(\s)([A-Z])(?=[a-z])/g, (_, space: string, letter: string) => space + letter.toLowerCase());

	function normalizeIncidentDefinitions(value: unknown): IncidentDefinition[] {
		if (!Array.isArray(value)) return [];
		const normalized = value
			.map((entry) => {
				if (!entry || typeof entry !== 'object') return null;
				const raw = entry as Record<string, unknown>;
				if (typeof raw.kind !== 'string' || typeof raw.label !== 'string') return null;
				return {
					kind: raw.kind,
					label: sentenceCase(raw.label),
					scope: typeof raw.scope === 'string' ? raw.scope : '',
					description:
						typeof raw.description === 'string' ? raw.description : 'Operator review required.',
					off_label: typeof raw.off_label === 'string' ? raw.off_label : 'Disabled',
					manual_label:
						typeof raw.manual_label === 'string' ? raw.manual_label : 'Operator reviews',
					automatic_label:
						typeof raw.automatic_label === 'string' ? raw.automatic_label : 'Automatic',
					automatic_supported: raw.automatic_supported === true,
					default: normalizeIncidentMode(raw.default)
				} satisfies IncidentDefinition;
			})
			.filter((entry): entry is IncidentDefinition => entry !== null);
		const seen = new Set<string>();
		return normalized.filter((entry) => {
			if (seen.has(entry.kind)) return false;
			seen.add(entry.kind);
			return true;
		});
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

	// What the default does, for the reset button's tooltip: "Automatic: turn
	// the channel forward until it clears."
	function defaultHelp(definition: IncidentDefinition): string {
		const label = {
			off: definition.off_label,
			manual: definition.manual_label,
			automatic: definition.automatic_label
		}[definition.default];
		const sentence = label.charAt(0).toLowerCase() + label.slice(1);
		return `${MODE_NAMES[definition.default]}: ${sentence}.`;
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

<div class="divide-y divide-line">
	{#each incidentDefinitions as definition (definition.kind)}
		<SettingRow
			label={definition.label}
			help={definition.description}
			changed={incidentMode(definition.kind) !== definition.default}
			defaultText={MODE_NAMES[definition.default]}
			defaultHelp={defaultHelp(definition)}
			onreset={() => void saveIncidentMode(definition.kind, definition.default)}
		>
			{#snippet tags()}
				{#if definition.scope}<Badge>{definition.scope}</Badge>{/if}
				{#if incidentDefinitionActive(definition)}<Badge tone="warning" dot>Active</Badge>{/if}
			{/snippet}
			<SegmentedControl
				label="When {definition.label} happens"
				size="sm"
				value={incidentMode(definition.kind)}
				onchange={(mode) => void saveIncidentMode(definition.kind, mode)}
				options={[
					{ value: 'off' as const, label: MODE_NAMES.off },
					{ value: 'manual' as const, label: MODE_NAMES.manual },
					...(definition.automatic_supported
						? [{ value: 'automatic' as const, label: MODE_NAMES.automatic }]
						: [])
				]}
			/>
		</SettingRow>
	{/each}
</div>
{#if incidentPolicyError}
	<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{incidentPolicyError}</Alert></div>
{/if}
