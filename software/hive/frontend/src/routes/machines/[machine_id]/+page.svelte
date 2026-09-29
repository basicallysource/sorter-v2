<script lang="ts">
	import { sentence } from '$lib/text';
	import { page } from '$app/state';
	import {
		api,
		type MachineOverview,
		type MachineConfigBackupSummary,
		type MachineConfigBackupDetail,
		type MachineCameraSpec
	} from '$lib/api';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import KeyValue from '$lib/components/KeyValue.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Stat from '$lib/components/Stat.svelte';
	import MachineWhereToFind from '$lib/components/MachineWhereToFind.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import AnalyticsDashboard from '$lib/components/charts/AnalyticsDashboard.svelte';
	import { localUiUrl } from '$lib/machineNetwork';

	const machineId = $derived(page.params.machine_id ?? '');

	let overview = $state<MachineOverview | null>(null);
	let backups = $state<MachineConfigBackupSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let expanded = $state<number | null>(null);
	let detail = $state<MachineConfigBackupDetail | null>(null);
	let detailLoading = $state(false);
	let openStateKey = $state<string | null>(null);

	const machine = $derived(overview?.machine ?? null);
	const stats = $derived(overview?.stats ?? null);
	const isOwner = $derived(overview?.is_owner ?? false);
	const specs = $derived(machine?.hardware_info ?? null);
	const cameraSpecs = $derived(Object.entries(specs?.cameras ?? {}));
	const boardSpecs = $derived(Object.entries(specs?.controller_boards ?? {}));
	const isOnline = $derived(
		!!machine?.last_seen_at && Date.now() - new Date(machine.last_seen_at).getTime() < 5 * 60 * 1000
	);
	const localUi = $derived(localUiUrl(machine?.network_info ?? null));
	const backLink = $derived(
		overview && !overview.is_owner && overview.viewer_is_admin
			? { href: '/admin/machines', label: 'All machines' }
			: { href: '/machines', label: 'My machines' }
	);

	function formatDate(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString() : '-';
	}
	function ppm(n: number | null | undefined): string {
		return n && n > 0 ? n.toFixed(1) : '-';
	}
	function pct(n: number | null | undefined): string {
		return n && n > 0 ? `${n.toFixed(1)}%` : '-';
	}
	function duration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '-';
		const h = seconds / 3600;
		if (h >= 1) return `${h.toFixed(1)}h`;
		return `${Math.round(seconds / 60)}m`;
	}

	function bytesToGb(n: number | null | undefined): string {
		if (!n || n <= 0) return '-';
		const gb = n / 1e9;
		return `${gb >= 100 ? Math.round(gb) : gb.toFixed(1)} GB`;
	}

	function resolution(cam: { width?: number | null; height?: number | null; fps?: number | null }): string {
		const res = cam.width && cam.height ? `${cam.width} x ${cam.height}` : null;
		const fps = cam.fps ? `${cam.fps} fps` : null;
		return [res, fps].filter(Boolean).join(', ') || '-';
	}

	// Color correction is a build-time kill switch on the machine, so a profile
	// can be calibrated and switched on locally yet still never touch a frame.
	// Report what actually happens, then what was configured.
	function colorCorrectionLabel(cam: MachineCameraSpec): string {
		const profile = cam.calibration?.color_profile;
		if (!profile) return 'Color: -';
		if (profile.applied) return 'Color: corrected';
		if (profile.globally_enabled === false) {
			return profile.calibrated
				? 'Color: off in this build (calibrated)'
				: 'Color: off in this build';
		}
		if (profile.calibrated) {
			return profile.enabled ? 'Color: corrected' : 'Color: off (calibrated)';
		}
		return 'Color: not calibrated';
	}

	function calibrationDetail(cam: MachineCameraSpec): string {
		const calibration = cam.calibration;
		if (!calibration) return '';
		const parts: string[] = [];
		const settings = calibration.device_settings;
		if (settings && Object.keys(settings).length > 0) {
			parts.push(`${Object.keys(settings).length} device settings`);
		}
		const picture = calibration.picture_settings;
		if (picture && Object.keys(picture).length > 0) parts.push('orientation set');
		return parts.join(', ');
	}

	function boardLabel(board: {
		family?: string | null;
		device_name?: string | null;
	}): string {
		return [board.device_name, board.family].filter(Boolean).join(', ') || '-';
	}

	function triggerVariant(trigger: string): 'success' | 'neutral' | 'warning' {
		if (trigger === 'manual') return 'warning';
		if (trigger === 'heartbeat') return 'neutral';
		return 'success';
	}

	$effect(() => {
		const id = machineId;
		if (!id) return;
		loading = true;
		error = null;
		backups = [];
		overview = null;
		api
			.getMachineOverview(id)
			.then((ov) => {
				overview = ov;
				// Config backups are owner-only on the backend; skip the call for
				// admins viewing someone else's machine.
				if (ov.is_owner) {
					return api.getMachineConfigBackups(id).then((list) => {
						backups = list;
					});
				}
			})
			.catch((err) => {
				error = (err as { error?: string }).error || 'Failed to load machine.';
			})
			.finally(() => {
				loading = false;
			});
	});

	async function toggle(version: number) {
		if (expanded === version) {
			expanded = null;
			detail = null;
			return;
		}
		expanded = version;
		detail = null;
		detailLoading = true;
		try {
			detail = await api.getMachineConfigBackup(machineId, version);
		} catch (err) {
			error = (err as { error?: string }).error || 'Failed to load backup detail.';
		} finally {
			detailLoading = false;
		}
	}

	function localStateKeys(d: MachineConfigBackupDetail): string[] {
		const ls = (d.payload?.local_state ?? {}) as Record<string, unknown>;
		return Object.entries(ls)
			.filter(([, v]) => v !== null && v !== undefined)
			.map(([k]) => k);
	}

	function localStateJson(d: MachineConfigBackupDetail, key: string): string {
		const ls = (d.payload?.local_state ?? {}) as Record<string, unknown>;
		try {
			return JSON.stringify(ls[key], null, 2);
		} catch {
			return String(ls[key]);
		}
	}

	function tomlText(d: MachineConfigBackupDetail): string {
		const t = d.payload?.toml_text;
		return typeof t === 'string' ? t : '';
	}
</script>

<svelte:head>
	<title>{machine ? machine.name : 'Machine'} - Hive</title>
</svelte:head>

<div class="mx-auto flex w-full max-w-5xl flex-col gap-(--gap-panels)">
	<div>
		<Button href={backLink.href} size="sm" variant="ghost" icon={ArrowLeft}>{backLink.label}</Button>
	</div>

	{#if loading}
		<div class="flex justify-center p-8"><Spinner size={32} /></div>
	{:else if error}
		<Alert tone="danger">{error}</Alert>
	{:else if overview && machine}
		<PageHeader title={machine.name} description={machine.description || undefined}>
			{#snippet actions()}
				<Button href={`/machines/${machine.id}/pieces`} icon={ArrowRight}>Pieces</Button>
				<Button href={`/machines/${machine.id}/channel-crops`} icon={ArrowRight}>Channel crops</Button>
				{#if localUi}
					<Button href={localUi} target="_blank" rel="noopener noreferrer" icon={ExternalLink}>Open its page</Button>
				{/if}
			{/snippet}
			<div class="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
				<Badge tone={isOnline ? 'success' : 'neutral'} dot>{isOnline ? 'Online' : 'Offline'}</Badge>
				{#if machine.archived_at}
					<Badge>Archived</Badge>
				{:else if !machine.is_active}
					<Badge>Inactive</Badge>
				{/if}
				{#if !isOwner && machine.owner.display_name}
					<span>
						Owner: <span class="text-ink">{machine.owner.display_name}</span>{#if machine.owner.email}, {machine.owner.email}{/if}
					</span>
				{/if}
			</div>
		</PageHeader>

		<Panel title="Machine" flush>
			<div class="px-(--pad-panel) pb-1">
				<KeyValue
					items={[
						{ label: 'Last seen', value: formatDate(machine.last_seen_at) },
						{ label: 'Registered', value: formatDate(machine.created_at) },
						{ label: 'Token', value: `${machine.token_prefix}...`, mono: true }
					]}
				/>
			</div>
		</Panel>

		<MachineWhereToFind
			info={machine.network_info}
			reportedAt={machine.network_reported_at}
			everSeen={!!machine.last_seen_at}
		/>

		<Panel
			title="Sorting"
			description="Pieces a minute and on time come from the synced pieces' times, not the machine's own clock."
			flush
		>
			<div class="overflow-hidden">
				<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
					{#each [
						{ label: 'Pieces counted', value: num(stats?.pieces_seen) },
						{ label: 'Distributed', value: num(stats?.distributed) },
						{ label: 'Pieces a minute', value: ppm(stats?.overall_ppm) },
						{ label: 'On time', value: pct(stats?.ontime_pct) },
						{ label: 'Active time', value: duration(stats?.active_seconds) },
						{ label: 'Classified', value: num(stats?.classified) },
						{ label: 'Unique parts', value: num(stats?.unique_parts) },
						{ label: 'Unique colors', value: num(stats?.unique_colors) }
					] as cell (cell.label)}
						<div class="border-t border-l border-line"><Stat label={cell.label} value={cell.value} /></div>
					{/each}
				</div>
			</div>
			<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
				First piece {formatDate(stats?.first_seen ?? null)}, last piece {formatDate(stats?.last_seen ?? null)}.
			</p>
		</Panel>

		<Panel title="Sample capture" flush>
			<div class="overflow-hidden">
				<div class="-mt-px -ml-px grid grid-cols-2 sm:grid-cols-4">
					{#each [
						{ label: 'Samples', value: num(stats?.total_samples) },
						{ label: 'Accepted', value: num(stats?.accepted_samples) },
						{ label: 'Sessions', value: num(stats?.total_sessions) },
						{
							label: 'Accept rate',
							value:
								stats && stats.total_samples > 0
									? `${Math.round((stats.accepted_samples / stats.total_samples) * 100)}%`
									: '-'
						}
					] as cell (cell.label)}
						<div class="border-t border-l border-line"><Stat label={cell.label} value={cell.value} /></div>
					{/each}
				</div>
			</div>
			{#if stats && stats.parts_needed > 0}
				<div class="border-t border-line px-(--pad-panel) py-3">
					<div class="mb-2 flex items-center justify-between text-sm">
						<span class="text-ink">Set parts found</span>
						<span class="num text-ink-muted"
							>{stats.parts_found} of {stats.parts_needed} ({Math.round(
								(stats.parts_found / stats.parts_needed) * 100
							)}%)</span
						>
					</div>
					<ProgressBar
						label="Set parts found"
						value={stats.parts_found}
						max={stats.parts_needed}
						tone="success"
					/>
				</div>
			{/if}
			<p class="border-t border-line px-(--pad-panel) py-3 text-sm text-ink-muted">
				First capture {formatDate(stats?.first_capture ?? null)}, last capture {formatDate(
					stats?.last_capture ?? null
				)}.{#if stats?.computed_at}{' '}Numbers as of {formatDate(stats.computed_at)}, refreshed hourly.{/if}
			</p>
		</Panel>

		<section class="flex flex-col gap-(--gap-panels)">
			<h2 class="text-base font-semibold text-ink">Analytics</h2>
			<AnalyticsDashboard machineId={machine.id} showTotals={false} />
		</section>

		{#if isOwner}
			<Panel
				title="Config backups"
				description="Versioned snapshots of this machine's settings. A new version is stored only when the settings change."
				flush
			>
				{#snippet actions()}
					<span class="num text-sm text-ink-muted"
						>{backups.length} version{backups.length === 1 ? '' : 's'}</span
					>
				{/snippet}
				{#if backups.length === 0}
					<div class="px-(--pad-panel) pb-(--pad-panel)">
						<EmptyState title="No backups yet">
							The machine sends one on its own once its settings are saved.
						</EmptyState>
					</div>
				{:else}
					<ul class="divide-y divide-line">
						{#each backups as backup (backup.id)}
							{@const open = expanded === backup.version}
							<li>
								<button
									type="button"
									aria-expanded={open}
									onclick={() => toggle(backup.version)}
									class="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-(--pad-panel) py-3 text-left hover:bg-hover"
								>
									<ChevronRight
										size={16}
										class="shrink-0 text-ink-muted transition-transform {open ? 'rotate-90' : ''}"
									/>
									<span class="num font-medium text-ink">v{backup.version}</span>
									<Badge tone={triggerVariant(backup.trigger)}>{sentence(backup.trigger)}</Badge>
									<span class="min-w-0 truncate text-sm text-ink-muted">{formatDate(backup.created_at)}</span>
									<span class="ml-auto font-mono text-sm text-ink-muted">{backup.content_hash.slice(0, 12)}</span>
								</button>
								{#if open}
									<div class="flex flex-col gap-3 px-(--pad-panel) pb-4 pl-11">
										{#if detailLoading}
											<div class="flex justify-center py-4"><Spinner size={24} /></div>
										{:else if detail}
											{@const d = detail}
											<div>
												<div class="label mb-1">Local state</div>
												{#if localStateKeys(d).length > 0}
													<ul class="divide-y divide-line">
														{#each localStateKeys(d) as key (key)}
															{@const keyOpen = openStateKey === key}
															<li>
																<button
																	type="button"
																	aria-expanded={keyOpen}
																	onclick={() => (openStateKey = keyOpen ? null : key)}
																	class="flex w-full items-center gap-2 py-2 text-left hover:bg-hover"
																>
																	<ChevronRight
																		size={14}
																		class="shrink-0 text-ink-muted transition-transform {keyOpen
																			? 'rotate-90'
																			: ''}"
																	/>
																	<span class="font-mono text-sm text-ink">{key}</span>
																</button>
																{#if keyOpen}
																	<pre
																		class="mb-2 max-h-80 overflow-auto rounded-control bg-well p-3 font-mono text-sm text-ink">{localStateJson(
																			d,
																			key
																		)}</pre>
																{/if}
															</li>
														{/each}
													</ul>
												{:else}
													<p class="text-sm text-ink-muted">No local state captured.</p>
												{/if}
											</div>
											<div>
												<div class="label mb-1 font-mono">machine_params.toml</div>
												<pre
													class="max-h-96 overflow-auto rounded-control bg-well p-3 font-mono text-sm text-ink">{tomlText(
														d
													) || '(empty)'}</pre>
											</div>
										{/if}
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</Panel>
		{/if}

		{#if specs && (isOwner || overview.viewer_is_admin)}
			<Panel
				title="Machine specs"
				description={specs.captured_at ? `As of ${formatDate(specs.captured_at)}.` : undefined}
				flush
			>
				<div class="px-(--pad-panel) pb-1">
					<KeyValue
						items={[
							{ label: 'Platform', value: specs.platform?.model || '-' },
							{
								label: 'Operating system',
								value: [specs.platform?.os?.name, specs.platform?.os?.sorter_os_version]
									.filter(Boolean)
									.join(', ') || '-'
							},
							{
								label: 'Software',
								value: [specs.software?.version, specs.software?.channel].filter(Boolean).join(', ') ||
									'-'
							},
							...(specs.system?.ram_bytes ? [{ label: 'Memory', value: bytesToGb(specs.system.ram_bytes) }] : []),
							...(specs.system?.disk_total_bytes
								? [{ label: 'Storage', value: bytesToGb(specs.system.disk_total_bytes) }]
								: []),
							...(specs.config?.machine_setup ? [{ label: 'Setup', value: specs.config.machine_setup }] : [])
						]}
					/>
				</div>
				{#if cameraSpecs.length > 0}
					<div class="border-t border-line px-(--pad-panel) py-3">
						<div class="label mb-1">Cameras</div>
						<ul class="divide-y divide-line">
							{#each cameraSpecs as [role, cam] (role)}
								<li class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-2.5 text-sm">
									<span class="text-ink">{sentence(role)}</span>
									<span class="text-right text-ink-muted">
										{cam.model || 'Camera'}, <span class="num">{resolution(cam)}</span>
										<span class="block">{colorCorrectionLabel(cam)}</span>
										{#if calibrationDetail(cam)}<span class="block">{calibrationDetail(cam)}</span>{/if}
									</span>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
				{#if boardSpecs.length > 0}
					<div class="border-t border-line px-(--pad-panel) pt-3 pb-1">
						<div class="label mb-1">Controller boards</div>
						<KeyValue
							items={boardSpecs.map(([key, board]) => ({
								label: sentence(board.role || key),
								value: boardLabel(board)
							}))}
						/>
					</div>
				{/if}
			</Panel>
		{/if}
	{/if}
</div>
