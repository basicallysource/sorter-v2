<script lang="ts">
	import { onMount } from 'svelte';
	import { Upload, RefreshCcw, Zap } from 'lucide-svelte';
	import { Alert, Button } from '$lib/components/primitives';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';

	type BoardVersion = {
		firmware_version?: string | null;
		variant?: string | null;
		commit?: string | null;
		build_time_utc?: string | null;
	} | null;

	type StepperInfo = {
		name: string | null;
		channel: number | null;
		microsteps: number | null;
		stallguard_enabled: boolean | null;
		stallguard_sgthrs: number | null;
		stallguard_tcoolthrs: number | null;
	};

	type Board = {
		device_name: string;
		family: string | null;
		role: string | null;
		port: string;
		address: number;
		version: BoardVersion;
		stepper_names: string[];
		steppers: StepperInfo[];
		source: 'live' | 'probe';
	};

	type BoardsResponse = {
		boards: Board[];
		hardware_state: string;
		bootloader_present: boolean;
		flash_allowed: boolean;
		flash_blocked_reason: string | null;
		active_job_id?: string;
	};

	type ReleaseAsset = {
		name: string;
		size: number | null;
		download_url: string;
		family: string;
		variant: string;
		role: string;
	};

	type Release = {
		tag: string;
		version: string;
		name: string | null;
		published_at: string | null;
		prerelease: boolean;
		changelog: { heading: string; entries: string[] } | null;
		assets: ReleaseAsset[];
	};

	type FlashJob = {
		job_id: string;
		created_ts: number;
		phase: string;
		progress: number | null;
		status: 'running' | 'done' | 'failed' | 'cancelled';
		error: string | null;
		retryable: boolean;
		log: string[];
		result: Record<string, any>;
		source: string;
		asset_name: string | null;
		release_tag: string | null;
		board_port: string | null;
		recovery: boolean;
	};

	type ConfigInfo = {
		hardware_state: string;
		no_power_development_mode: boolean;
		machine_setup: string | null;
		feeder_mode: string | null;
		classification_channel_mode: string | null;
		machine_toml_present?: boolean;
	};

	const manager = getMachinesContext();

	let boards = $state<Board[]>([]);
	let boardsMeta = $state<BoardsResponse | null>(null);
	let boardsLoading = $state(false);
	let boardsError = $state<string | null>(null);

	let config = $state<ConfigInfo | null>(null);

	let releases = $state<Release[]>([]);
	let releasesLoading = $state(false);
	let releasesError = $state<string | null>(null);

	let selectedBoardKey = $state<string | null>(null);
	let selectedReleaseTag = $state<string | null>(null);
	let selectedAssetName = $state<string | null>(null);
	let recoveryMode = $state(false);

	let uploadInput = $state<HTMLInputElement | null>(null);
	let uploading = $state(false);
	let uploadedFile = $state<{ upload_id: string; filename: string; size: number } | null>(null);
	let flashSource = $state<'release' | 'upload'>('release');

	let job = $state<FlashJob | null>(null);
	let jobPollTimer: ReturnType<typeof setInterval> | null = null;
	let startingFlash = $state(false);
	let flashError = $state<string | null>(null);
	let resetting = $state(false);

	const PHASE_LABELS: Record<string, string> = {
		queued: 'Queued',
		downloading: 'Downloading firmware',
		identifying: 'Identifying board',
		rebooting: 'Rebooting into bootloader',
		waiting_bootloader: 'Waiting for bootloader drive',
		copying: 'Copying firmware',
		waiting_reboot: 'Waiting for board reboot',
		verifying: 'Verifying new firmware',
		done: 'Done'
	};

	function baseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function readErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {
			/* fall through */
		}
		try {
			return await res.text();
		} catch {
			return `Request failed with status ${res.status}`;
		}
	}

	function boardKey(board: Board): string {
		return `${board.port}@${board.address}`;
	}

	const selectedBoard = $derived(boards.find((b) => boardKey(b) === selectedBoardKey) ?? null);

	const selectedRelease = $derived(
		releases.find((r) => r.tag === selectedReleaseTag) ?? null
	);

	const selectedAsset = $derived(
		selectedRelease?.assets.find((a) => a.name === selectedAssetName) ?? null
	);

	const jobActive = $derived(job !== null && job.status === 'running');

	const flashAllowed = $derived(boardsMeta?.flash_allowed ?? false);

	function suggestAssetForBoard(release: Release, board: Board | null): ReleaseAsset | null {
		if (!release.assets.length) return null;
		if (board) {
			const variant = board.version?.variant ?? null;
			if (variant) {
				const exact = release.assets.find((a) => a.variant === variant);
				if (exact) return exact;
			}
			if (board.role) {
				const byRole = release.assets.find((a) => a.role === board.role);
				if (byRole) return byRole;
			}
		}
		return release.assets[0];
	}

	async function loadBoards(refresh = false) {
		boardsLoading = true;
		boardsError = null;
		try {
			const res = await fetch(`${baseUrl()}/api/firmware/boards${refresh ? '?refresh=true' : ''}`);
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload: BoardsResponse = await res.json();
			boardsMeta = payload;
			boards = payload.boards;
			if (boards.length && !boards.some((b) => boardKey(b) === selectedBoardKey)) {
				selectedBoardKey = boardKey(boards[0]);
			}
		} catch (e: any) {
			boardsError = e?.message ?? 'Failed to load boards';
		} finally {
			boardsLoading = false;
		}
	}

	async function loadConfig() {
		try {
			const res = await fetch(`${baseUrl()}/api/firmware/config`);
			if (!res.ok) return;
			config = await res.json();
		} catch {
			/* non-critical */
		}
	}

	async function loadReleases(refresh = false) {
		releasesLoading = true;
		releasesError = null;
		try {
			const res = await fetch(
				`${baseUrl()}/api/firmware/releases${refresh ? '?refresh=true' : ''}`
			);
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			releases = Array.isArray(payload?.releases) ? payload.releases : [];
			if (releases.length && !releases.some((r) => r.tag === selectedReleaseTag)) {
				selectedReleaseTag = releases[0].tag;
			}
		} catch (e: any) {
			releasesError = e?.message ?? 'Failed to load releases';
		} finally {
			releasesLoading = false;
		}
	}

	$effect(() => {
		const release = selectedRelease;
		if (!release) return;
		if (!release.assets.some((a) => a.name === selectedAssetName)) {
			selectedAssetName = suggestAssetForBoard(release, selectedBoard)?.name ?? null;
		}
	});

	async function loadLatestJob() {
		try {
			const res = await fetch(`${baseUrl()}/api/firmware/flash/jobs`);
			if (!res.ok) return;
			const payload = await res.json();
			const jobs: FlashJob[] = Array.isArray(payload?.jobs) ? payload.jobs : [];
			if (jobs.length) {
				job = jobs[0];
				if (job.status === 'running') startJobPolling(job.job_id);
			}
		} catch {
			/* non-critical */
		}
	}

	function stopJobPolling() {
		if (jobPollTimer) {
			clearInterval(jobPollTimer);
			jobPollTimer = null;
		}
	}

	function startJobPolling(jobId: string) {
		stopJobPolling();
		jobPollTimer = setInterval(async () => {
			try {
				const res = await fetch(`${baseUrl()}/api/firmware/flash/${jobId}`);
				if (!res.ok) return;
				const payload: FlashJob = await res.json();
				job = payload;
				if (payload.status !== 'running') {
					stopJobPolling();
					void loadBoards(true);
				}
			} catch {
				/* transient; keep polling */
			}
		}, 500);
	}

	async function handleUpload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		uploading = true;
		flashError = null;
		try {
			const res = await fetch(
				`${baseUrl()}/api/firmware/upload?filename=${encodeURIComponent(file.name)}`,
				{
					method: 'POST',
					headers: { 'Content-Type': 'application/octet-stream' },
					body: file
				}
			);
			if (!res.ok) throw new Error(await readErrorMessage(res));
			uploadedFile = await res.json();
			flashSource = 'upload';
		} catch (e: any) {
			flashError = e?.message ?? 'Upload failed';
		} finally {
			uploading = false;
		}
	}

	async function startFlash() {
		if (jobActive) return;
		flashError = null;

		const body: Record<string, any> = { recovery: recoveryMode };
		if (flashSource === 'upload') {
			if (!uploadedFile) {
				flashError = 'Upload a .uf2 file first.';
				return;
			}
			body.source = 'upload';
			body.upload_id = uploadedFile.upload_id;
			body.asset_name = uploadedFile.filename;
		} else {
			if (!selectedAsset || !selectedRelease) {
				flashError = 'Pick a release and firmware file first.';
				return;
			}
			body.source = 'release';
			body.asset_url = selectedAsset.download_url;
			body.asset_name = selectedAsset.name;
			body.release_tag = selectedRelease.tag;
		}
		if (!recoveryMode) {
			if (!selectedBoard) {
				flashError = 'Select a board to flash.';
				return;
			}
			body.board_port = selectedBoard.port;
			body.expected_device_name = selectedBoard.device_name;
		}

		startingFlash = true;
		try {
			const res = await fetch(`${baseUrl()}/api/firmware/flash`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			job = payload.job;
			startJobPolling(payload.job_id);
		} catch (e: any) {
			flashError = e?.message ?? 'Failed to start flash';
		} finally {
			startingFlash = false;
		}
	}

	async function retryJob() {
		if (!job || job.status === 'running') return;
		flashError = null;
		try {
			const res = await fetch(`${baseUrl()}/api/firmware/flash/${job.job_id}/retry`, {
				method: 'POST'
			});
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			job = payload.job;
			startJobPolling(payload.job_id);
		} catch (e: any) {
			flashError = e?.message ?? 'Retry failed';
		}
	}

	async function cancelJob() {
		if (!job || job.status !== 'running') return;
		try {
			await fetch(`${baseUrl()}/api/firmware/flash/${job.job_id}/cancel`, { method: 'POST' });
		} catch {
			/* poll will pick up the outcome */
		}
	}

	async function resetToStandby() {
		resetting = true;
		flashError = null;
		try {
			const res = await fetch(`${baseUrl()}/api/system/reset`, { method: 'POST' });
			if (!res.ok) throw new Error(await readErrorMessage(res));
			const payload = await res.json();
			if (payload?.ok === false) throw new Error(payload?.message ?? 'Reset refused');
			await loadBoards(true);
		} catch (e: any) {
			flashError = e?.message ?? 'Reset failed';
		} finally {
			resetting = false;
		}
	}

	function formatBytes(size: number | null | undefined): string {
		if (!size && size !== 0) return '';
		if (size < 1024) return `${size} B`;
		if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
		return `${(size / (1024 * 1024)).toFixed(2)} MB`;
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		try {
			return new Date(iso).toLocaleDateString();
		} catch {
			return iso;
		}
	}

	let loadedMachineKey = $state<string | null>(null);
	$effect(() => {
		const machineKey = manager.selectedMachine?.url ?? '__local__';
		if (machineKey !== loadedMachineKey) {
			loadedMachineKey = machineKey;
			void loadBoards();
			void loadConfig();
			void loadReleases();
			void loadLatestJob();
		}
	});

	onMount(() => {
		return () => stopJobPolling();
	});
</script>

<div class="flex flex-col gap-4">
	<SectionCard
		title="Connected Boards"
		description="Control boards discovered over USB, with the firmware each one is running."
	>
		{#snippet headerActions()}
			<Button
				variant="secondary"
				size="sm"
				loading={boardsLoading}
				onclick={() => void loadBoards(true)}
			>
				<RefreshCcw class="h-3.5 w-3.5" />
				Refresh
			</Button>
		{/snippet}

		{#if boardsError}
			<Alert variant="danger">{boardsError}</Alert>
		{:else if boardsLoading && !boards.length}
			<div class="flex items-center gap-2 py-4 text-sm text-text-muted">
				<Spinner /> Scanning for boards…
			</div>
		{:else if !boards.length}
			<Alert variant="warning">
				No control boards responded over USB.
				{#if boardsMeta?.flash_blocked_reason}
					{boardsMeta.flash_blocked_reason}
				{/if}
				{#if boardsMeta?.bootloader_present}
					A board in bootloader mode (RPI-RP2) is present — use a recovery flash below.
				{/if}
			</Alert>
		{:else}
			<div class="flex flex-col gap-3">
				{#each boards as board (boardKey(board))}
					<div class="border border-border bg-surface p-3">
						<div class="flex flex-wrap items-baseline justify-between gap-2">
							<div class="flex items-baseline gap-2">
								<span class="text-sm font-semibold text-text">{board.device_name}</span>
								{#if board.role}
									<span
										class="border border-border px-1.5 py-0.5 text-xs uppercase tracking-wider text-text-muted"
									>
										{board.role}
									</span>
								{/if}
								{#if board.source === 'live'}
									<span class="text-xs text-text-muted">(active hardware)</span>
								{/if}
							</div>
							<span class="text-xs text-text-muted">{board.port} · address {board.address}</span>
						</div>
						<dl class="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
							<div>
								<dt class="text-xs uppercase tracking-wider text-text-muted">Firmware</dt>
								<dd class="text-text">
									{board.version?.firmware_version ?? 'unknown (no GET_VERSION)'}
								</dd>
							</div>
							<div>
								<dt class="text-xs uppercase tracking-wider text-text-muted">Variant</dt>
								<dd class="text-text">{board.version?.variant ?? '—'}</dd>
							</div>
							<div>
								<dt class="text-xs uppercase tracking-wider text-text-muted">Built</dt>
								<dd class="text-text">{board.version?.build_time_utc ?? '—'}</dd>
							</div>
							{#if board.version?.commit}
								<div>
									<dt class="text-xs uppercase tracking-wider text-text-muted">Commit</dt>
									<dd class="font-mono text-text">{board.version.commit}</dd>
								</div>
							{/if}
							{#if board.stepper_names.length}
								<div class="col-span-2">
									<dt class="text-xs uppercase tracking-wider text-text-muted">Steppers</dt>
									<dd class="text-text">{board.stepper_names.join(', ')}</dd>
								</div>
							{/if}
						</dl>
					</div>
				{/each}
			</div>
		{/if}

		{#if config}
			<div class="mt-3 border-t border-border pt-3">
				<dl class="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
					<div>
						<dt class="text-xs uppercase tracking-wider text-text-muted">Hardware state</dt>
						<dd class="text-text">{boardsMeta?.hardware_state ?? config.hardware_state}</dd>
					</div>
					{#if config.machine_setup}
						<div>
							<dt class="text-xs uppercase tracking-wider text-text-muted">Machine setup</dt>
							<dd class="text-text">{config.machine_setup}</dd>
						</div>
					{/if}
					{#if config.feeder_mode}
						<div>
							<dt class="text-xs uppercase tracking-wider text-text-muted">Feeder mode</dt>
							<dd class="text-text">{config.feeder_mode}</dd>
						</div>
					{/if}
					{#if config.classification_channel_mode}
						<div>
							<dt class="text-xs uppercase tracking-wider text-text-muted">Classification</dt>
							<dd class="text-text">{config.classification_channel_mode}</dd>
						</div>
					{/if}
				</dl>
			</div>
		{/if}
	</SectionCard>

	<SectionCard
		title="Flash Firmware"
		description="Flash a firmware release from GitHub or an uploaded .uf2. The machine must be in standby."
	>
		{#if boardsMeta && !flashAllowed && !jobActive}
			<Alert variant="warning" class="mb-3">
				<div class="flex flex-wrap items-center justify-between gap-2">
					<span>{boardsMeta.flash_blocked_reason ?? 'Flashing is currently unavailable.'}</span>
					{#if (boardsMeta.hardware_state === 'ready' || boardsMeta.hardware_state === 'initialized') && !jobActive}
						<Button variant="secondary" size="sm" loading={resetting} onclick={resetToStandby}>
							Reset to standby
						</Button>
					{/if}
				</div>
			</Alert>
		{/if}

		<div class="flex flex-col gap-4">
			<div class="grid gap-4 sm:grid-cols-2">
				<div class="flex flex-col gap-1.5">
					<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Target board
					</span>
					<select
						class="setup-control"
						bind:value={selectedBoardKey}
						disabled={recoveryMode || jobActive || !boards.length}
					>
						{#each boards as board (boardKey(board))}
							<option value={boardKey(board)}>
								{board.device_name} — {board.port}
								{board.version?.firmware_version ? ` (${board.version.firmware_version})` : ''}
							</option>
						{/each}
						{#if !boards.length}
							<option value={null}>No boards found</option>
						{/if}
					</select>
					<label class="mt-1 flex items-center gap-2 text-sm text-text">
						<input type="checkbox" bind:checked={recoveryMode} disabled={jobActive} />
						Recovery flash — board is already in bootloader (RPI-RP2), or blank
					</label>
				</div>

				<div class="flex flex-col gap-1.5">
					<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						Firmware source
					</span>
					<div class="flex gap-3 text-sm text-text">
						<label class="flex items-center gap-1.5">
							<input type="radio" bind:group={flashSource} value="release" disabled={jobActive} />
							GitHub release
						</label>
						<label class="flex items-center gap-1.5">
							<input type="radio" bind:group={flashSource} value="upload" disabled={jobActive} />
							Upload .uf2
						</label>
					</div>
					{#if flashSource === 'release'}
						{#if releasesError}
							<Alert variant="danger">{releasesError}</Alert>
						{:else}
							<select
								class="setup-control"
								bind:value={selectedReleaseTag}
								disabled={jobActive || releasesLoading}
							>
								{#each releases as release (release.tag)}
									<option value={release.tag}>
										{release.version}
										{release.published_at ? ` — ${formatDate(release.published_at)}` : ''}
										{release.prerelease ? ' (pre-release)' : ''}
									</option>
								{/each}
							</select>
							{#if selectedRelease}
								<select
									class="setup-control"
									bind:value={selectedAssetName}
									disabled={jobActive}
								>
									{#each selectedRelease.assets as asset (asset.name)}
										<option value={asset.name}>
											{asset.name}
											{asset.size ? ` (${formatBytes(asset.size)})` : ''}
										</option>
									{/each}
								</select>
							{/if}
						{/if}
					{:else}
						<div class="flex items-center gap-2">
							<Button
								variant="secondary"
								size="sm"
								loading={uploading}
								disabled={jobActive}
								onclick={() => uploadInput?.click()}
							>
								<Upload class="h-3.5 w-3.5" />
								Choose .uf2
							</Button>
							{#if uploadedFile}
								<span class="text-sm text-text-muted">
									{uploadedFile.filename} ({formatBytes(uploadedFile.size)})
								</span>
							{/if}
						</div>
						<input
							bind:this={uploadInput}
							type="file"
							accept=".uf2"
							class="hidden"
							onchange={handleUpload}
						/>
					{/if}
				</div>
			</div>

			{#if flashSource === 'release' && selectedRelease?.changelog}
				<div class="border border-border bg-surface p-3">
					<p class="text-xs font-semibold uppercase tracking-wider text-text-muted">
						{selectedRelease.changelog.heading}
					</p>
					<ul class="mt-1.5 list-disc pl-5 text-sm text-text">
						{#each selectedRelease.changelog.entries as entry}
							<li>{entry}</li>
						{/each}
					</ul>
				</div>
			{/if}

			{#if flashError}
				<Alert variant="danger">{flashError}</Alert>
			{/if}

			<div>
				<Button
					variant="primary"
					loading={startingFlash}
					disabled={jobActive || (!flashAllowed && !recoveryMode)}
					onclick={startFlash}
				>
					<Zap class="h-4 w-4" />
					{recoveryMode ? 'Recovery flash' : 'Flash firmware'}
				</Button>
			</div>
		</div>
	</SectionCard>

	{#if job}
		<SectionCard title="Flash Progress" description="">
			<div class="flex flex-col gap-3">
				<div class="flex flex-wrap items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						{#if job.status === 'running'}
							<Spinner />
						{/if}
						<span class="text-sm font-semibold text-text">
							{PHASE_LABELS[job.phase] ?? job.phase}
						</span>
						<span class="text-xs uppercase tracking-wider text-text-muted">{job.status}</span>
					</div>
					<div class="flex gap-2">
						{#if job.status === 'running'}
							<Button variant="secondary" size="sm" onclick={cancelJob}>Cancel</Button>
						{:else if job.retryable}
							<Button variant="secondary" size="sm" onclick={retryJob}>Retry</Button>
						{/if}
					</div>
				</div>

				{#if job.status === 'running'}
					<div class="h-2 w-full bg-border">
						{#if job.progress !== null}
							<div class="h-full bg-primary" style="width: {Math.round(job.progress * 100)}%"></div>
						{:else}
							<div class="h-full w-1/4 animate-pulse bg-primary"></div>
						{/if}
					</div>
				{/if}

				{#if job.status === 'done'}
					<Alert variant="success">
						Flash complete.
						{#if job.result?.board?.version?.firmware_version}
							Board reports firmware {job.result.board.version.firmware_version}.
						{/if}
						The machine is in standby — home it from the main page when you're ready.
					</Alert>
				{:else if job.status === 'failed'}
					<Alert variant="danger">{job.error ?? 'Flash failed.'}</Alert>
				{:else if job.status === 'cancelled'}
					<Alert variant="warning">{job.error ?? 'Flash cancelled.'}</Alert>
				{/if}

				{#if job.log.length}
					<div class="max-h-48 overflow-y-auto border border-border bg-surface p-2">
						{#each job.log as line}
							<p class="font-mono text-xs leading-relaxed text-text-muted">{line}</p>
						{/each}
					</div>
				{/if}
			</div>
		</SectionCard>
	{/if}
</div>
