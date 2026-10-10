<script lang="ts">
	import { confirmDialog } from '$lib/confirm.svelte';
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import {
		beginHiveLink,
		completeReturnedHiveLink,
		DEFAULT_HIVE_URL,
		defaultHiveTargetName
	} from '$lib/hive/link-flow';
	import Cloud from '@lucide/svelte/icons/cloud';
	import Link2 from '@lucide/svelte/icons/link-2';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Plus from '@lucide/svelte/icons/plus';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Shield from '@lucide/svelte/icons/shield';
	import Star from '@lucide/svelte/icons/star';
	import Trash2 from '@lucide/svelte/icons/trash';
	import MachineNameField from '$lib/components/MachineNameField.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';

	const machine = getMachineContext();

	// What each Hive sends back in its heartbeat reply, and what this machine
	// may send it in return.
	type HiveLimits = {
		sample_burst_interval_s: number;
		sample_floor_interval_s: number;
		sample_ramp_hours: number;
		sample_store_max_bytes: number;
		upload_bytes_per_minute: number;
		upload_files_per_minute: number;
	};

	type SyncStatus = {
		enabled: boolean;
		// null until the first heartbeat has been answered or failed.
		server_reachable: boolean | null;
		last_beat_at: number | null;
		// Rows or files still to upload per data type; null = not known yet.
		waiting: Record<string, number | null>;
		// Data types this Hive does not accept yet.
		unsupported: string[];
		upload_budget: {
			bytes_per_minute: number;
			files_per_minute: number;
			bytes_available: number;
			files_available: number;
		} | null;
		last_error: string | null;
		limits: HiveLimits | null;
	};

	type HiveTarget = {
		id: string;
		name: string;
		url: string;
		machine_id: string | null;
		api_token_masked: string | null;
		enabled: boolean;
		is_primary: boolean;
		telemetry: Record<string, boolean>;
		sync: SyncStatus;
	};

	type HiveConfig = {
		configured_count: number;
		enabled_count: number;
		primary_target_id: string | null;
		targets: HiveTarget[];
	};

	type LegacyHiveConfig = {
		configured?: boolean;
		url?: string;
		machine_id?: string | null;
		api_token_masked?: string | null;
		enabled?: boolean;
	};

	type TelemetryField = {
		key: string;
		label: string;
		description: string;
	};

	let config = $state<HiveConfig | null>(null);
	let telemetryFields = $state<TelemetryField[]>([]);
	let uploadsTargetId = $state<string | null>(null);
	let telemetrySaving = $state(false);
	let loading = $state(true);
	let statusMsg = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);

	let editingTargetId = $state<string | null>(null);
	let showRegisterForm = $state(false);
	let savingTarget = $state(false);
	let removingTargetId = $state<string | null>(null);
	let registering = $state(false);

	let targetName = $state('');
	let targetUrl = $state('');
	let targetToken = $state('');
	let targetEnabled = $state(true);

	let regTargetName = $state('');
	let regUrl = $state('');
	let regEmail = $state('');
	let regPassword = $state('');
	let regMachineName = $state('');
	let regMachineDescription = $state('');

	let showPairForm = $state(false);
	let pairing = $state(false);
	let pairUrl = $state(DEFAULT_HIVE_URL);
	let pairTargetName = $state('');
	let pairMachineName = $state('');

	const targets = $derived(config?.targets ?? []);

	function normalizeTelemetry(raw: unknown): Record<string, boolean> {
		if (!raw || typeof raw !== 'object') return {};
		return Object.fromEntries(
			Object.entries(raw as Record<string, unknown>).filter(
				([, value]) => typeof value === 'boolean'
			)
		) as Record<string, boolean>;
	}

	function emptySyncStatus(enabled: boolean): SyncStatus {
		return {
			enabled,
			server_reachable: null,
			last_beat_at: null,
			waiting: {},
			unsupported: [],
			upload_budget: null,
			last_error: null,
			limits: null
		};
	}

	function normalizeConfig(raw: unknown): HiveConfig {
		if (!raw || typeof raw !== 'object') {
			return { configured_count: 0, enabled_count: 0, primary_target_id: null, targets: [] };
		}

		const data = raw as Record<string, unknown>;
		const primaryTargetId =
			typeof data.primary_target_id === 'string' ? data.primary_target_id : null;
		if (Array.isArray(data.targets)) {
			const normalizedTargets = data.targets.flatMap((entry, index) => {
				if (!entry || typeof entry !== 'object') return [];
				const target = entry as Record<string, unknown>;
				const enabled = Boolean(target.enabled);
				const syncRaw =
					target.sync && typeof target.sync === 'object'
						? (target.sync as Partial<SyncStatus>)
						: null;
				return [
					{
						id:
							typeof target.id === 'string' && target.id.trim() ? target.id : `target-${index + 1}`,
						name:
							typeof target.name === 'string' && target.name.trim()
								? target.name
								: typeof target.url === 'string'
									? target.url
									: `Hive ${index + 1}`,
						url: typeof target.url === 'string' ? target.url : '',
						machine_id: typeof target.machine_id === 'string' ? target.machine_id : null,
						api_token_masked:
							typeof target.api_token_masked === 'string' ? target.api_token_masked : null,
						enabled,
						is_primary: Boolean(target.is_primary),
						telemetry: normalizeTelemetry(target.telemetry),
						sync: {
							...emptySyncStatus(enabled),
							...(syncRaw ?? {})
						}
					} satisfies HiveTarget
				];
			});

			const resolvedPrimaryId =
				primaryTargetId && normalizedTargets.some((t) => t.id === primaryTargetId)
					? primaryTargetId
					: (normalizedTargets[0]?.id ?? null);

			return {
				configured_count: normalizedTargets.length,
				enabled_count: normalizedTargets.filter((target) => target.enabled).length,
				primary_target_id: resolvedPrimaryId,
				targets: normalizedTargets.map((t) => ({
					...t,
					is_primary: t.id === resolvedPrimaryId
				}))
			};
		}

		const legacy = data as LegacyHiveConfig;
		const configured =
			Boolean(legacy.configured) ||
			(typeof legacy.url === 'string' && legacy.url.trim().length > 0);
		if (!configured || typeof legacy.url !== 'string' || !legacy.url.trim()) {
			return { configured_count: 0, enabled_count: 0, primary_target_id: null, targets: [] };
		}

		const enabled = Boolean(legacy.enabled);
		return {
			configured_count: 1,
			enabled_count: enabled ? 1 : 0,
			primary_target_id: 'legacy-target',
			targets: [
				{
					id: 'legacy-target',
					name: legacy.url,
					url: legacy.url,
					machine_id: typeof legacy.machine_id === 'string' ? legacy.machine_id : null,
					api_token_masked:
						typeof legacy.api_token_masked === 'string' ? legacy.api_token_masked : null,
					enabled,
					is_primary: true,
					telemetry: {},
					sync: emptySyncStatus(enabled)
				}
			]
		};
	}

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function getTarget(targetId: string | null): HiveTarget | null {
		if (!targetId) return null;
		return targets.find((target) => target.id === targetId) ?? null;
	}

	function clearMessages() {
		statusMsg = null;
		errorMsg = null;
	}

	function resetTargetForm(target: HiveTarget | null = null) {
		targetName = target?.name ?? '';
		targetUrl = target?.url ?? '';
		targetToken = '';
		targetEnabled = target?.enabled ?? true;
	}

	function resetRegisterForm() {
		regTargetName = '';
		regUrl = '';
		regEmail = '';
		regPassword = '';
		regMachineName = '';
		regMachineDescription = '';
	}

	function parseTelemetryFields(raw: unknown): TelemetryField[] {
		const data = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
		if (!Array.isArray(data.telemetry_fields)) return [];
		return data.telemetry_fields.flatMap((entry) => {
			if (!entry || typeof entry !== 'object') return [];
			const field = entry as Record<string, unknown>;
			if (typeof field.key !== 'string' || typeof field.label !== 'string') return [];
			return [
				{
					key: field.key,
					label: field.label,
					description: typeof field.description === 'string' ? field.description : ''
				}
			];
		});
	}

	function targetAllows(target: HiveTarget, key: string): boolean {
		return target.telemetry[key] !== false;
	}

	async function postTelemetry(target: HiveTarget, body: Record<string, unknown>) {
		telemetrySaving = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/telemetry`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target_id: target.id, ...body })
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			const telemetry = normalizeTelemetry(data?.telemetry);
			if (config) {
				config = {
					...config,
					targets: config.targets.map((t) => (t.id === target.id ? { ...t, telemetry } : t))
				};
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to update upload settings.';
		} finally {
			telemetrySaving = false;
		}
	}

	function handleToggleTelemetry(target: HiveTarget, field: TelemetryField) {
		void postTelemetry(target, { fields: { [field.key]: !targetAllows(target, field.key) } });
	}

	function handleResetTelemetry(target: HiveTarget) {
		void postTelemetry(target, { reset: true });
	}

	async function loadConfig() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`);
			if (!res.ok) throw new Error(await res.text());
			const raw = await res.json();
			config = normalizeConfig(raw);
			telemetryFields = parseTelemetryFields(raw);

			if (editingTargetId) {
				resetTargetForm(getTarget(editingTargetId));
			}
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to load Hive config.';
		} finally {
			loading = false;
		}
	}

	function openTargetEditor(target: HiveTarget | null = null) {
		clearMessages();
		showRegisterForm = false;
		editingTargetId = target?.id ?? 'new';
		resetTargetForm(target);
	}

	function openRegisterForm() {
		clearMessages();
		editingTargetId = null;
		showRegisterForm = true;
		showPairForm = false;
		resetRegisterForm();
	}

	function resetPairForm() {
		pairUrl = DEFAULT_HIVE_URL;
		pairTargetName = '';
		pairMachineName = '';
	}

	function openPairForm() {
		clearMessages();
		editingTargetId = null;
		showRegisterForm = false;
		showPairForm = true;
		resetPairForm();
	}

	function closeForms() {
		editingTargetId = null;
		showRegisterForm = false;
		showPairForm = false;
		resetTargetForm();
		resetRegisterForm();
		resetPairForm();
	}

	function handlePair() {
		if (!pairUrl.trim()) return;
		pairing = true;
		clearMessages();
		try {
			beginHiveLink({
				hiveUrl: pairUrl.trim(),
				targetName: pairTargetName.trim() || undefined,
				machineName: pairMachineName.trim() || undefined,
				returnPath: window.location.pathname + window.location.search
			});
		} catch (e: any) {
			errorMsg = e?.message ?? 'Could not start the Hive link flow.';
			pairing = false;
		}
	}

	async function handleSaveTarget() {
		if (!targetUrl.trim()) return;
		const existing =
			editingTargetId && editingTargetId !== 'new' ? getTarget(editingTargetId) : null;
		if (!existing && !targetToken.trim()) return;

		savingTarget = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					id: existing?.id ?? null,
					name: targetName.trim(),
					url: targetUrl.trim(),
					api_token: targetToken.trim(),
					enabled: targetEnabled
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = existing
				? targetToken.trim()
					? `Updated Hive target "${targetName.trim() || existing.name}".`
					: `Updated Hive target "${targetName.trim() || existing.name}" and kept the current token.`
				: `Added Hive target "${targetName.trim() || targetUrl.trim()}".`;
			closeForms();
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to save Hive target.';
		} finally {
			savingTarget = false;
		}
	}

	async function handleRemoveTarget(target: HiveTarget) {
		if (
			!(await confirmDialog({
				title: 'Remove the Hive target?',
				message: `Remove "${target.name}" from this sorter?`,
				action: 'Remove the target',
				danger: true
			}))
		)
			return;
		removingTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/settings/hive?target_id=${encodeURIComponent(target.id)}`,
				{ method: 'DELETE' }
			);
			if (!res.ok) throw new Error(await res.text());
			statusMsg = `Removed Hive target "${target.name}".`;
			if (editingTargetId === target.id) {
				closeForms();
			}
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to remove Hive target.';
		} finally {
			removingTargetId = null;
		}
	}

	let settingPrimaryTargetId = $state<string | null>(null);

	async function handleSetPrimary(target: HiveTarget) {
		if (target.is_primary) return;
		settingPrimaryTargetId = target.id;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/primary`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target_id: target.id })
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = `"${target.name}" is now the primary Hive (used for piece metadata).`;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to set primary Hive target.';
		} finally {
			settingPrimaryTargetId = null;
		}
	}

	async function handleRegister() {
		if (!regUrl.trim() || !regEmail.trim() || !regPassword.trim() || !regMachineName.trim()) return;
		registering = true;
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive/register`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					target_name: regTargetName.trim(),
					url: regUrl.trim(),
					email: regEmail.trim(),
					password: regPassword.trim(),
					machine_name: regMachineName.trim(),
					machine_description: regMachineDescription.trim()
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			statusMsg = `Registered "${data.machine_name}" for target "${data.target_name}".`;
			showRegisterForm = false;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Registration failed.';
		} finally {
			registering = false;
		}
	}

	async function handleToggleEnabled(target: HiveTarget) {
		clearMessages();
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/settings/hive`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					id: target.id,
					name: target.name,
					url: target.url,
					api_token: '',
					enabled: !target.enabled
				})
			});
			if (!res.ok) throw new Error(await res.text());
			statusMsg = !target.enabled
				? `Enabled live samples to "${target.name}".`
				: `Stopped live samples to "${target.name}".`;
			await loadConfig();
		} catch (e: any) {
			errorMsg = e.message ?? 'Failed to update sample target state.';
		}
	}

	function statusLabel(target: HiveTarget): string {
		if (!target.enabled) return 'Connected, live samples off';
		if (target.sync.server_reachable) return 'Receiving live samples';
		return 'Connected, waiting for server';
	}

	function statusTone(target: HiveTarget): 'success' | 'warning' {
		return target.enabled && target.sync.server_reachable ? 'success' : 'warning';
	}

	const DATA_TYPES: [key: string, label: string][] = [
		['piece_records', 'Piece records'],
		['piece_corrections', 'Corrections'],
		['piece_images', 'Piece images'],
		['channel_crops', 'Channel crops'],
		['control_data_segments', 'Control data'],
		['samples', 'Training samples']
	];

	function unsupportedText(target: HiveTarget): string {
		return target.sync.unsupported
			.map((key) => (DATA_TYPES.find(([k]) => k === key)?.[1] ?? key).toLowerCase())
			.join(' or ');
	}

	// Only the types this machine knows the count for.
	function waitingStats(target: HiveTarget): { label: string; count: number }[] {
		return DATA_TYPES.flatMap(([key, label]) => {
			const count = target.sync.waiting[key];
			return typeof count === 'number' ? [{ label, count }] : [];
		});
	}

	function limitItems(target: HiveTarget) {
		const limits = target.sync.limits;
		if (!limits) return [];
		const megabytes = Math.round(limits.upload_bytes_per_minute / 1e5) / 10;
		return [
			{
				label: 'Upload budget',
				value: `${megabytes} MB and ${limits.upload_files_per_minute} files a minute`
			},
			{
				label: 'Fastest sampling',
				value: `Every ${Math.round(limits.sample_burst_interval_s * 10) / 10} s`
			}
		];
	}

	function targetMenu(target: HiveTarget) {
		return [
			{
				label: removingTargetId === target.id ? 'Removing' : 'Remove this Hive',
				icon: Trash2,
				danger: true,
				disabled: removingTargetId === target.id,
				onselect: () => void handleRemoveTarget(target)
			}
		];
	}

	async function handleReturnedLink() {
		try {
			const result = await completeReturnedHiveLink(currentBackendBaseUrl());
			if (result.completed) {
				statusMsg = result.message ?? 'Hive link saved.';
				await loadConfig();
			}
		} catch (e: any) {
			errorMsg = e?.message ?? 'Hive link could not be completed.';
		}
	}

	onMount(() => {
		void loadConfig();
		void handleReturnedLink();
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if loading}
		<div class="flex items-center gap-2 text-sm text-ink-muted">
			<Spinner size={14} /> Loading the Hive settings
		</div>
	{:else if config}
		<div class="flex flex-wrap items-center justify-between gap-3">
			<p class="text-sm text-ink-muted">
				{#if targets.length > 0}
					{config.enabled_count} of {config.configured_count}
					{config.configured_count === 1 ? 'Hive gets' : 'Hives get'} live samples.
				{:else}
					No Hive set up yet.
				{/if}
			</p>
			<div class="flex flex-wrap items-center gap-2">
				<Button
					variant="ghost"
					icon={RefreshCw}
					label="Refresh"
					onclick={() => void loadConfig()}
				/>
				<Button icon={Cloud} onclick={() => openTargetEditor(null)}>Add an existing token</Button>
				<Button
					icon={Plus}
					onclick={openRegisterForm}
				>
					Register (legacy)
				</Button>
				<Button variant="primary" icon={Link2} onclick={openPairForm}>Pair with Hive</Button>
			</div>
		</div>

		{#if errorMsg}
			<Alert tone="danger">{errorMsg}</Alert>
		{/if}
		{#if statusMsg}
			<Alert tone="success">{statusMsg}</Alert>
		{/if}

		{#if targets.length === 0}
			<EmptyState icon={Cloud} title="No Hive yet">
				Pair with a Hive for testing, production, or both, and turn on the ones that should get live
				samples from C2, C3 and C4.
			</EmptyState>
		{:else}
			{#each targets as target (target.id)}
				<Panel flush>
					<div class="flex flex-wrap items-start justify-between gap-3 px-(--pad-panel) pt-4 pb-3">
						<div class="min-w-0">
							<div class="flex flex-wrap items-center gap-2">
								<h2 class="text-base font-semibold text-ink">{target.name}</h2>
								{#if target.is_primary}
									<Badge tone="primary"><Star size={12} /> Primary</Badge>
								{/if}
								<Badge tone={statusTone(target)} dot>{statusLabel(target)}</Badge>
							</div>
							{#if target.is_primary}
								<p class="mt-0.5 text-sm text-ink-muted">
									Used for piece metadata lookups, such as dimensions.
								</p>
							{/if}
						</div>
						<div class="flex flex-wrap items-center gap-2">
							{#if !target.is_primary}
								<Button
									size="sm"
									icon={Star}
									loading={settingPrimaryTargetId === target.id}
									onclick={() => void handleSetPrimary(target)}
								>
									Make primary
								</Button>
							{/if}
							<Button size="sm" icon={Pencil} onclick={() => openTargetEditor(target)}>Edit</Button>
							<Button
								size="sm"
								icon={Shield}
								onclick={() => {
									clearMessages();
									uploadsTargetId = target.id;
								}}
							>
								Uploads
							</Button>
							<Button
								size="sm"
								variant={target.enabled ? 'secondary' : 'primary'}
								onclick={() => void handleToggleEnabled(target)}
							>
								{target.enabled ? 'Stop samples' : 'Send samples'}
							</Button>
							<Menu label="More for {target.name}" items={targetMenu(target)}>
								{#snippet trigger(props)}
									<Button {...props} size="sm" variant="ghost" icon={Ellipsis} label="More" />
								{/snippet}
							</Menu>
						</div>
					</div>

					<div class="px-(--pad-panel)">
						<KeyValue
							items={[
								{ label: 'Server', value: target.url, mono: true },
								{ label: 'Machine ID', value: target.machine_id ?? 'None', mono: true },
								{ label: 'Token', value: target.api_token_masked ?? 'None', mono: true },
								...limitItems(target)
							]}
						/>
					</div>

					<div class="border-t border-line">
						<div class="label px-(--pad-panel) pt-3 pb-2">Waiting to upload</div>
						{#if waitingStats(target).length > 0}
							<div class="flex flex-wrap gap-px border-t border-line bg-line">
								{#each waitingStats(target) as stat (stat.label)}
									<div class="grow basis-36 bg-surface">
										<Stat label={stat.label} value={stat.count.toLocaleString()} />
									</div>
								{/each}
							</div>
						{:else}
							<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
								The counts appear once this Hive has answered.
							</p>
						{/if}
					</div>
					{#if target.sync.unsupported.length > 0}
						<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
							This Hive does not accept {unsupportedText(target)} yet.
						</p>
					{/if}
					{#if target.sync.last_error}
						<p class="border-t border-line px-(--pad-panel) py-3 text-sm break-words text-warning-ink">
							{target.sync.last_error}
						</p>
					{/if}
				</Panel>
			{/each}
		{/if}

		{#if editingTargetId !== null}
			<Modal
				open={true}
				title={editingTargetId === 'new'
					? 'Add a Hive'
					: `Edit ${getTarget(editingTargetId)?.name ?? 'the Hive'}`}
				onclose={closeForms}
			>
				<div class="flex flex-col gap-4">
					<Field label="Name" for="hive-target-name">
						<Input id="hive-target-name" bind:value={targetName} placeholder="Local, or Live" />
					</Field>
					<Field label="Server" for="hive-target-url">
						<Input
							id="hive-target-url"
							type="url"
							bind:value={targetUrl}
							placeholder="https://hive.example.com"
						/>
					</Field>
					<Field
						label="Machine token"
						for="hive-target-token"
						help={editingTargetId === 'new' ? undefined : 'Leave it empty to keep the current token.'}
					>
						<Input
							id="hive-target-token"
							type="password"
							bind:value={targetToken}
							class="font-mono"
						/>
					</Field>
					<Checkbox bind:checked={targetEnabled}>Send live samples to this Hive right away</Checkbox>
				</div>
				{#snippet footer()}
					<Button variant="ghost" onclick={closeForms}>Cancel</Button>
					<Button
						variant="primary"
						loading={savingTarget}
						disabled={!targetUrl.trim() || (editingTargetId === 'new' && !targetToken.trim())}
						onclick={() => void handleSaveTarget()}
					>
						Save
					</Button>
				{/snippet}
			</Modal>
		{/if}

		{#if getTarget(uploadsTargetId)}
			{@const uploadsTarget = getTarget(uploadsTargetId)!}
			<Modal open={true} title="Uploads to {uploadsTarget.name}" onclose={() => (uploadsTargetId = null)}>
				<p class="text-ink-muted">
					What this Sorter may upload to this Hive. Anything unchecked never leaves the machine.
					Changes apply at once, including to uploads already queued.
				</p>
				<div class="mt-4 flex flex-col gap-3">
					{#each telemetryFields as field (field.key)}
						<div>
							<Checkbox
								checked={targetAllows(uploadsTarget, field.key)}
								disabled={telemetrySaving}
								onchange={() => handleToggleTelemetry(uploadsTarget, field)}
							>
								<span class="font-medium">{field.label}</span>
							</Checkbox>
							<p class="mt-0.5 ml-6.5 text-sm text-ink-muted">{field.description}</p>
						</div>
					{/each}
				</div>
				{#snippet footer()}
					<Button
						variant="ghost"
						class="mr-auto"
						disabled={telemetrySaving}
						onclick={() => handleResetTelemetry(uploadsTarget)}
					>
						Reset to the defaults
					</Button>
					<Button variant="primary" onclick={() => (uploadsTargetId = null)}>Done</Button>
				{/snippet}
			</Modal>
		{/if}

		{#if showPairForm}
			<Modal open={true} title="Pair with a Hive" onclose={closeForms}>
				<p class="text-ink-muted">
					Enter the Hive's address, then pick a name for this machine on Hive. Hive sends you back
					here once the link is saved; no email or password leaves this Sorter.
				</p>
				<div class="mt-4 flex flex-col gap-4">
					<Field label="Hive" for="pair-url">
						<Input id="pair-url" type="url" bind:value={pairUrl} placeholder={DEFAULT_HIVE_URL} />
					</Field>
					<Field label="Name for this Hive" for="pair-name" help="Optional.">
						<Input
							id="pair-name"
							bind:value={pairTargetName}
							placeholder={pairUrl.trim() ? defaultHiveTargetName(pairUrl) : 'Hive Community'}
						/>
					</Field>
					<Field
						label="Suggested machine name"
						for="pair-machine-name"
						help="Optional: Hive names the machine if you leave it blank."
					>
						<MachineNameField
							id="pair-machine-name"
							bind:value={pairMachineName}
							backendBaseUrl={currentBackendBaseUrl()}
						/>
					</Field>
				</div>
				{#snippet footer()}
					<Button variant="ghost" onclick={closeForms}>Cancel</Button>
					<Button
						variant="primary"
						icon={Link2}
						loading={pairing}
						disabled={!pairUrl.trim()}
						onclick={handlePair}
					>
						Continue on Hive
					</Button>
				{/snippet}
			</Modal>
		{/if}

		{#if showRegisterForm}
			<Modal open={true} title="Register a new machine on a Hive" onclose={closeForms}>
				<div class="flex flex-col gap-4">
					<Field label="Name for this Hive" for="reg-name">
						<Input id="reg-name" bind:value={regTargetName} placeholder="Local, or Live" />
					</Field>
					<Field label="Hive" for="reg-url">
						<Input id="reg-url" type="url" bind:value={regUrl} placeholder="https://hive.example.com" />
					</Field>
					<Field label="Account email" for="reg-email">
						<Input id="reg-email" type="email" bind:value={regEmail} />
					</Field>
					<Field label="Account password" for="reg-password">
						<Input id="reg-password" type="password" bind:value={regPassword} />
					</Field>
					<Field label="Machine name" for="reg-machine-name">
						<MachineNameField
							id="reg-machine-name"
							bind:value={regMachineName}
							backendBaseUrl={currentBackendBaseUrl()}
						/>
					</Field>
					<Field label="Machine description" for="reg-description" help="Optional.">
						<Input id="reg-description" bind:value={regMachineDescription} />
					</Field>
				</div>
				{#snippet footer()}
					<Button variant="ghost" onclick={closeForms}>Cancel</Button>
					<Button
						variant="primary"
						loading={registering}
						disabled={!regUrl.trim() ||
							!regEmail.trim() ||
							!regPassword.trim() ||
							!regMachineName.trim()}
						onclick={() => void handleRegister()}
					>
						Register
					</Button>
				{/snippet}
			</Modal>
		{/if}
	{:else}
		{#if errorMsg}
			<Alert tone="danger">{errorMsg}</Alert>
		{/if}
	{/if}
</div>
