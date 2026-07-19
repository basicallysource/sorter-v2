<script lang="ts">
	import { page } from '$app/state';
	import {
		api,
		type MachineOverview,
		type MachineConfigBackupSummary,
		type MachineConfigBackupDetail,
		type MachineCameraSpec
	} from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Alert } from '$lib/components/primitives';
	import AnalyticsDashboard from '$lib/components/charts/AnalyticsDashboard.svelte';

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
	const backLink = $derived(
		overview && !overview.is_owner && overview.viewer_is_admin
			? { href: '/admin/machines', label: '← All machines' }
			: { href: '/machines', label: '← My Machines' }
	);

	function formatDate(iso: string | null): string {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('de-DE', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function num(n: number | null | undefined): string {
		return n != null ? Math.round(n).toLocaleString() : '—';
	}
	function ppm(n: number | null | undefined): string {
		return n && n > 0 ? n.toFixed(1) : '—';
	}
	function pct(n: number | null | undefined): string {
		return n && n > 0 ? `${n.toFixed(1)}%` : '—';
	}
	function duration(seconds: number | null | undefined): string {
		if (!seconds || seconds <= 0) return '—';
		const h = seconds / 3600;
		if (h >= 1) return `${h.toFixed(1)}h`;
		return `${Math.round(seconds / 60)}m`;
	}

	function prettyRole(role: string): string {
		return role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
	}

	function bytesToGb(n: number | null | undefined): string {
		if (!n || n <= 0) return '—';
		const gb = n / 1e9;
		return `${gb >= 100 ? Math.round(gb) : gb.toFixed(1)} GB`;
	}

	function resolution(cam: { width?: number | null; height?: number | null; fps?: number | null }): string {
		const res = cam.width && cam.height ? `${cam.width}×${cam.height}` : null;
		const fps = cam.fps ? `${cam.fps} fps` : null;
		return [res, fps].filter(Boolean).join(' · ') || '—';
	}

	// Color correction is a build-time kill switch on the machine, so a profile
	// can be calibrated and switched on locally yet still never touch a frame.
	// Report what actually happens, then what was configured.
	function colorCorrectionLabel(cam: MachineCameraSpec): string {
		const profile = cam.calibration?.color_profile;
		if (!profile) return 'Color: —';
		if (profile.applied) return 'Color: corrected';
		if (profile.globally_enabled === false) {
			return profile.calibrated
				? 'Color: off in build (calibrated)'
				: 'Color: off in build';
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
		return parts.join(' · ');
	}

	function boardLabel(board: {
		family?: string | null;
		device_name?: string | null;
	}): string {
		return [board.device_name, board.family].filter(Boolean).join(' · ') || '—';
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
	<title>{machine ? `${machine.name} — Overview` : 'Machine'} · Hive</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-8">
	<a href={backLink.href} class="text-sm text-text-muted hover:text-primary hover:underline">{backLink.label}</a>

	{#if loading}
		<div class="mt-8 flex justify-center"><Spinner /></div>
	{:else if error}
		<div class="mt-6"><Alert variant="danger">{error}</Alert></div>
	{:else if overview && machine}
		<!-- Header -->
		<header class="mt-3 border border-border bg-surface p-5">
			<div class="flex items-start justify-between gap-4">
				<div class="min-w-0">
					<div class="flex items-center gap-2">
						<span class="inline-block h-2.5 w-2.5 rounded-full {isOnline ? 'bg-success' : 'bg-border'}"></span>
						<h1 class="truncate text-xl font-semibold text-text">{machine.name}</h1>
						<span class="text-[10px] font-medium uppercase tracking-wider {isOnline ? 'text-success' : 'text-text-muted'}">
							{isOnline ? 'Online' : 'Offline'}
						</span>
					</div>
					{#if machine.description}
						<p class="mt-1 text-sm text-text-muted">{machine.description}</p>
					{/if}
					{#if !isOwner && machine.owner.display_name}
						<p class="mt-1 text-xs text-text-muted">
							Owner: <span class="text-text">{machine.owner.display_name}</span>
							{#if machine.owner.email}<span class="text-text-muted"> · {machine.owner.email}</span>{/if}
						</p>
					{/if}
				</div>
				<div class="flex shrink-0 items-center gap-2">
					{#if machine.archived_at}
						<Badge text="Archived" variant="neutral" />
					{:else}
						<Badge text={machine.is_active ? 'Active' : 'Inactive'} variant={machine.is_active ? 'success' : 'neutral'} />
					{/if}
				</div>
			</div>

			<dl class="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
				<div>
					<dt class="text-text-muted">Last seen</dt>
					<dd class="text-text">{formatDate(machine.last_seen_at)}</dd>
				</div>
				<div>
					<dt class="text-text-muted">Registered</dt>
					<dd class="text-text">{formatDate(machine.created_at)}</dd>
				</div>
				<div>
					<dt class="text-text-muted">Token</dt>
					<dd class="text-text">{machine.token_prefix}…</dd>
				</div>
				<div>
					<dt class="text-text-muted">Local UI</dt>
					<dd class="text-text">
						{#if machine.last_seen_ip}
							<a
								href={`http://${machine.last_seen_ip}:${machine.local_ui_port || '8000'}`}
								target="_blank"
								rel="noopener noreferrer"
								class="text-primary hover:underline">Open ↗</a
							>
						{:else}
							—
						{/if}
					</dd>
				</div>
			</dl>
		</header>

		<!-- Piece stats -->
		<section class="mt-6">
			<div class="flex items-baseline justify-between">
				<h2 class="text-lg font-semibold text-text">Sorting</h2>
				<div class="flex items-baseline gap-4">
					<a
						href={`/machines/${machine.id}/channel-crops`}
						class="text-sm text-primary hover:underline">Channel crops →</a
					>
					<a
						href={`/machines/${machine.id}/pieces`}
						class="text-sm text-primary hover:underline">View pieces →</a
					>
				</div>
			</div>
			<div class="mt-3 grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-4">
				{#each [
					{ label: 'Pieces counted', value: num(stats?.pieces_seen) },
					{ label: 'Distributed', value: num(stats?.distributed) },
					{ label: 'Parts / min', value: ppm(stats?.overall_ppm) },
					{ label: 'On-time', value: pct(stats?.ontime_pct) },
					{ label: 'Active time', value: duration(stats?.active_seconds) },
					{ label: 'Classified', value: num(stats?.classified) },
					{ label: 'Unique parts', value: num(stats?.unique_parts) },
					{ label: 'Unique colors', value: num(stats?.unique_colors) }
				] as cell (cell.label)}
					<div class="flex flex-col items-center bg-surface py-4">
						<span class="text-xl font-bold text-text tabular-nums">{cell.value}</span>
						<span class="mt-0.5 text-[10px] uppercase tracking-wider text-text-muted">{cell.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-xs text-text-muted">
				First piece {formatDate(stats?.first_seen ?? null)} · Last piece {formatDate(stats?.last_seen ?? null)}.
				PPM and on-time are inferred from synced piece timestamps (active sorting from piece density),
				not the machine's exact powered clock.
			</p>
		</section>

		<!-- Sample capture -->
		<section class="mt-6">
			<h2 class="text-lg font-semibold text-text">Sample capture</h2>
			<div class="mt-3 grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-4">
				{#each [
					{ label: 'Samples', value: num(stats?.total_samples) },
					{ label: 'Accepted', value: num(stats?.accepted_samples) },
					{ label: 'Sessions', value: num(stats?.total_sessions) },
					{
						label: 'Accept rate',
						value:
							stats && stats.total_samples > 0
								? `${Math.round((stats.accepted_samples / stats.total_samples) * 100)}%`
								: '—'
					}
				] as cell (cell.label)}
					<div class="flex flex-col items-center bg-surface py-4">
						<span class="text-xl font-bold text-text tabular-nums">{cell.value}</span>
						<span class="mt-0.5 text-[10px] uppercase tracking-wider text-text-muted">{cell.label}</span>
					</div>
				{/each}
			</div>
			{#if stats && stats.parts_needed > 0}
				{@const found = stats.parts_found}
				{@const needed = stats.parts_needed}
				{@const p = Math.round((found / needed) * 100)}
				<div class="mt-3 border border-border bg-surface px-4 py-3">
					<div class="mb-1.5 flex items-center justify-between text-xs">
						<span class="font-medium text-text">Set parts found</span>
						<span class="font-mono text-text-muted">{found}/{needed} ({p}%)</span>
					</div>
					<div class="h-2 w-full bg-border">
						<div class="h-full bg-success transition-all" style="width: {p}%"></div>
					</div>
				</div>
			{/if}
			<p class="mt-2 text-xs text-text-muted">
				First capture {formatDate(stats?.first_capture ?? null)} · Last capture {formatDate(stats?.last_capture ?? null)}.
			</p>
		</section>

		{#if stats?.computed_at}
			<p class="mt-4 text-xs text-text-muted">Stats as of {formatDate(stats.computed_at)} (refreshed hourly).</p>
		{/if}

		<!-- Analytics (charts) -->
		<section class="mt-8">
			<h2 class="mb-3 text-lg font-semibold text-text">Analytics</h2>
			<AnalyticsDashboard machineId={machine.id} showTotals={false} />
		</section>

		<!-- Config backups (owner only) -->
		{#if isOwner}
			<section class="mt-8">
				<div class="flex items-baseline justify-between">
					<h2 class="text-lg font-semibold text-text">Config backups</h2>
					<span class="text-sm text-text-muted">{backups.length} version{backups.length === 1 ? '' : 's'}</span>
				</div>
				<p class="mt-1 text-sm text-text-muted">
					Versioned snapshots of this machine's settings. A new version is stored only when the config
					actually changes.
				</p>

				{#if backups.length === 0}
					<div class="mt-4 border border-border bg-surface p-6 text-center text-sm text-text-muted">
						No backups yet. The machine pushes one automatically once its settings are saved.
					</div>
				{:else}
					<div class="mt-4 border border-border bg-surface">
						{#each backups as backup (backup.id)}
							<div class="border-b border-border last:border-b-0">
								<button
									type="button"
									onclick={() => toggle(backup.version)}
									class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-bg"
								>
									<span class="font-mono text-sm font-semibold text-text">v{backup.version}</span>
									<Badge text={backup.trigger} variant={triggerVariant(backup.trigger)} />
									<span class="text-sm text-text-muted">{formatDate(backup.created_at)}</span>
									<span class="ml-auto font-mono text-xs text-text-muted">{backup.content_hash.slice(0, 12)}</span>
									<span class="text-text-muted">{expanded === backup.version ? '▾' : '▸'}</span>
								</button>
								{#if expanded === backup.version}
									<div class="border-t border-border bg-bg px-4 py-3">
										{#if detailLoading}
											<div class="flex justify-center py-4"><Spinner /></div>
										{:else if detail}
											<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
												local_state
											</div>
											{#if localStateKeys(detail).length > 0}
												<div class="mb-4 border border-border">
													{#each localStateKeys(detail) as key (key)}
														{@const d = detail}
														<div class="border-b border-border last:border-b-0">
															<button
																type="button"
																onclick={() => (openStateKey = openStateKey === key ? null : key)}
																class="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface"
															>
																<span class="font-mono text-xs text-text">{key}</span>
																<span class="ml-auto text-text-muted">{openStateKey === key ? '▾' : '▸'}</span>
															</button>
															{#if openStateKey === key}
																<pre class="max-h-80 overflow-auto border-t border-border bg-surface p-3 text-xs text-text">{localStateJson(d, key)}</pre>
															{/if}
														</div>
													{/each}
												</div>
											{:else}
												<p class="mb-4 text-sm text-text-muted">No local_state captured.</p>
											{/if}
											<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
												machine_params.toml
											</div>
											<pre class="max-h-96 overflow-auto border border-border bg-surface p-3 text-xs text-text">{tomlText(detail) || '(empty)'}</pre>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</section>
		{/if}

		<!-- Machine specs (owner + admins only; the page itself is already owner/admin-gated) -->
		{#if specs && (isOwner || overview.viewer_is_admin)}
			<section class="mt-8">
				<h2 class="text-lg font-semibold text-text">Machine specs</h2>
				<div class="mt-3 border border-border bg-surface p-5">
					<dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
						<div>
							<dt class="text-text-muted">Platform</dt>
							<dd class="text-text">{specs.platform?.model || '—'}</dd>
						</div>
						<div>
							<dt class="text-text-muted">Operating system</dt>
							<dd class="text-text">
								{specs.platform?.os?.name || '—'}
								{#if specs.platform?.os?.sorter_os_version}
									<span class="text-text-muted"> · {specs.platform.os.sorter_os_version}</span>
								{/if}
							</dd>
						</div>
						<div>
							<dt class="text-text-muted">Software</dt>
							<dd class="text-text">
								{specs.software?.version || '—'}
								{#if specs.software?.channel}
									<span class="text-text-muted"> · {specs.software.channel}</span>
								{/if}
							</dd>
						</div>
						{#if specs.system?.ram_bytes}
							<div>
								<dt class="text-text-muted">Memory</dt>
								<dd class="text-text">{bytesToGb(specs.system.ram_bytes)}</dd>
							</div>
						{/if}
						{#if specs.system?.disk_total_bytes}
							<div>
								<dt class="text-text-muted">Storage</dt>
								<dd class="text-text">{bytesToGb(specs.system.disk_total_bytes)}</dd>
							</div>
						{/if}
						{#if specs.config?.machine_setup}
							<div>
								<dt class="text-text-muted">Setup</dt>
								<dd class="text-text">{specs.config.machine_setup}</dd>
							</div>
						{/if}
					</dl>

					{#if cameraSpecs.length > 0}
						<div class="mt-5 border-t border-border pt-4">
							<h3 class="text-xs font-medium uppercase tracking-wider text-text-muted">Cameras</h3>
							<dl class="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
								{#each cameraSpecs as [role, cam] (role)}
									<div>
										<dt class="text-text">{prettyRole(role)}</dt>
										<dd class="text-text-muted">
											{cam.model || 'Camera'}
											<span class="block tabular-nums">{resolution(cam)}</span>
											<span class="block">{colorCorrectionLabel(cam)}</span>
											{#if calibrationDetail(cam)}
												<span class="block">{calibrationDetail(cam)}</span>
											{/if}
										</dd>
									</div>
								{/each}
							</dl>
						</div>
					{/if}

					{#if boardSpecs.length > 0}
						<div class="mt-5 border-t border-border pt-4">
							<h3 class="text-xs font-medium uppercase tracking-wider text-text-muted">Controller boards</h3>
							<dl class="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
								{#each boardSpecs as [key, board] (key)}
									<div>
										<dt class="text-text">{prettyRole(board.role || key)}</dt>
										<dd class="text-text-muted">{boardLabel(board)}</dd>
									</div>
								{/each}
							</dl>
						</div>
					{/if}

					{#if specs.captured_at}
						<p class="mt-4 text-xs text-text-muted">As of {formatDate(specs.captured_at)}.</p>
					{/if}
				</div>
			</section>
		{/if}
	{/if}
</div>
