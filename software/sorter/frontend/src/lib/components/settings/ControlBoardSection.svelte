<script lang="ts">
	import { onMount } from 'svelte';
	import Upload from '@lucide/svelte/icons/upload';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import Zap from '@lucide/svelte/icons/zap';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
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

	const manager = getMachinesContext();

	let boards = $state<Board[]>([]);
	let boardsMeta = $state<BoardsResponse | null>(null);
	let boardsLoading = $state(false);
	let boardsError = $state<string | null>(null);

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

	// The board kits ship with. A blank board, or one in its bootloader, cannot
	// say what it is, and the first asset in a release is an older board's.
	const KIT_BOARD_VARIANT = 'distribution-v1-2';

	function suggestAssetForBoard(release: Release, board: Board | null): ReleaseAsset | null {
		if (!release.assets.length) return null;
		const kit = release.assets.find((a) => a.variant === KIT_BOARD_VARIANT) ?? null;
		if (!board) return kit ?? release.assets[0];
		const variant = board.version?.variant ?? null;
		const exact = variant ? release.assets.find((a) => a.variant === variant) : undefined;
		if (exact) return exact;
		const sameKind = release.assets.filter((a) => a.family === board.family && a.role === board.role);
		return sameKind.find((a) => a === kit) ?? sameKind[0] ?? kit ?? release.assets[0];
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
			void loadReleases();
			void loadLatestJob();
		}
	});

	onMount(() => {
		return () => stopJobPolling();
	});
</script>

<Panel
	title="Connected boards"
	description="The control boards found over USB, and the firmware each one runs."
	flush
>
	{#snippet actions()}
		<Button size="sm" icon={RefreshCcw} loading={boardsLoading} onclick={() => void loadBoards(true)}>
			Refresh
		</Button>
	{/snippet}
	{#if boardsError}
		<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{boardsError}</Alert></div>
	{:else if boardsLoading && !boards.length}
		<div class="flex items-center gap-2 px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
			<Spinner size={14} /> Looking for boards
		</div>
	{:else if !boards.length}
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			<Alert tone="warning">
				No control board answered over USB.
				{#if boardsMeta?.flash_blocked_reason}{boardsMeta.flash_blocked_reason}{/if}
				{#if boardsMeta?.bootloader_present}
					A board in bootloader mode (RPI-RP2) is there: use a recovery flash below.
				{/if}
			</Alert>
		</div>
	{:else}
		<ul class="divide-y divide-line">
			{#each boards as board (boardKey(board))}
				<li class="px-(--pad-panel) py-(--pad-row)">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<div class="flex flex-wrap items-center gap-2">
							<span class="text-sm font-semibold text-ink">{board.device_name}</span>
							{#if board.role}<Badge>{board.role}</Badge>{/if}
							{#if board.source === 'live'}<Badge tone="success" dot>In use</Badge>{/if}
						</div>
						<span class="font-mono text-sm text-ink-muted">{board.port}, address {board.address}</span>
					</div>
					<dl class="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
						<div>
							<dt class="text-ink-muted">Firmware</dt>
							<dd class="text-ink">{board.version?.firmware_version ?? 'Unknown (no GET_VERSION)'}</dd>
						</div>
						<div>
							<dt class="text-ink-muted">Variant</dt>
							<dd class="text-ink">{board.version?.variant ?? 'None'}</dd>
						</div>
						<div>
							<dt class="text-ink-muted">Built</dt>
							<dd class="text-ink">{board.version?.build_time_utc ?? 'Unknown'}</dd>
						</div>
						{#if board.version?.commit}
							<div>
								<dt class="text-ink-muted">Commit</dt>
								<dd class="font-mono text-ink">{board.version.commit}</dd>
							</div>
						{/if}
						{#if board.stepper_names.length}
							<div class="col-span-2">
								<dt class="text-ink-muted">Steppers</dt>
								<dd class="text-ink">{board.stepper_names.join(', ')}</dd>
							</div>
						{/if}
					</dl>
				</li>
			{/each}
		</ul>
	{/if}
</Panel>

<Panel
	title="Flash firmware"
	description="Flash a firmware release from GitHub, or a .uf2 file you upload. The machine has to be in standby."
>
	<div class="flex flex-col gap-4">
		{#if boardsMeta && !flashAllowed && !jobActive}
			<Alert tone="warning">
				{boardsMeta.flash_blocked_reason ?? "Flashing isn't possible right now."}
				{#snippet actions()}
					{#if boardsMeta?.hardware_state === 'ready' || boardsMeta?.hardware_state === 'initialized'}
						<Button size="sm" loading={resetting} onclick={resetToStandby}>Reset to standby</Button>
					{/if}
				{/snippet}
			</Alert>
		{/if}

		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
			<div class="flex flex-col gap-3">
				<Field label="Board" for="flash-board">
					<Select
						id="flash-board"
						value={selectedBoardKey ?? undefined}
						onchange={(key) => (selectedBoardKey = key)}
						disabled={recoveryMode || jobActive || !boards.length}
						placeholder="No boards found"
						options={boards.map((board) => ({
							value: boardKey(board),
							label: `${board.device_name}, ${board.port}${board.version?.firmware_version ? ` (${board.version.firmware_version})` : ''}`
						}))}
					/>
				</Field>
				<Checkbox bind:checked={recoveryMode} disabled={jobActive}>
					Recovery flash: the board is already in its bootloader (RPI-RP2), or blank
				</Checkbox>
			</div>

			<div class="flex flex-col gap-3">
				<div class="flex flex-col gap-1.5">
					<span class="text-sm font-medium text-ink">Firmware</span>
					<SegmentedControl
						label="Firmware source"
						bind:value={flashSource}
						options={[
							{ value: 'release', label: 'A GitHub release' },
							{ value: 'upload', label: 'A .uf2 file' }
						]}
					/>
				</div>
				{#if flashSource === 'release'}
					{#if releasesError}
						<Alert tone="danger">{releasesError}</Alert>
					{:else if !releasesLoading && !releases.length}
						<Alert tone="warning">No firmware releases on GitHub. Upload a .uf2 file instead.</Alert>
					{:else}
						<Select
							label="Release"
							value={selectedReleaseTag ?? undefined}
							onchange={(tag) => (selectedReleaseTag = tag)}
							disabled={jobActive || releasesLoading}
							options={releases.map((release) => ({
								value: release.tag,
								label: `${release.version}${release.published_at ? `, ${formatDate(release.published_at)}` : ''}${release.prerelease ? ' (pre-release)' : ''}`
							}))}
						/>
						{#if selectedRelease}
							<Select
								label="File"
								value={selectedAssetName ?? undefined}
								onchange={(name) => (selectedAssetName = name)}
								disabled={jobActive}
								options={selectedRelease.assets.map((asset) => ({
									value: asset.name,
									label: `${asset.name}${asset.size ? ` (${formatBytes(asset.size)})` : ''}`
								}))}
							/>
						{/if}
					{/if}
				{:else}
					<div class="flex items-center gap-2">
						<Button
							icon={Upload}
							loading={uploading}
							disabled={jobActive}
							onclick={() => uploadInput?.click()}
						>
							Choose a .uf2 file
						</Button>
						{#if uploadedFile}
							<span class="text-sm text-ink-muted">
								{uploadedFile.filename} ({formatBytes(uploadedFile.size)})
							</span>
						{/if}
					</div>
					<input bind:this={uploadInput} type="file" accept=".uf2" class="hidden" onchange={handleUpload} />
				{/if}
			</div>
		</div>

		{#if flashSource === 'release' && selectedRelease?.changelog}
			<div class="rounded-control bg-well p-3">
				<p class="label">{selectedRelease.changelog.heading}</p>
				<ul class="mt-1.5 list-disc pl-5 text-sm text-ink">
					{#each selectedRelease.changelog.entries as entry}
						<li>{entry}</li>
					{/each}
				</ul>
			</div>
		{/if}

		{#if flashError}
			<Alert tone="danger">{flashError}</Alert>
		{/if}
	</div>
	{#snippet footer()}
		<Button
			variant="primary"
			icon={Zap}
			loading={startingFlash}
			disabled={jobActive || (!flashAllowed && !recoveryMode)}
			onclick={startFlash}
		>
			{recoveryMode ? 'Recovery flash' : 'Flash the firmware'}
		</Button>
	{/snippet}
</Panel>

{#if job}
	<Panel title="Flashing">
		{#snippet actions()}
			{#if job?.status === 'running'}
				<Button size="sm" onclick={cancelJob}>Cancel</Button>
			{:else if job?.retryable}
				<Button size="sm" onclick={retryJob}>Retry</Button>
			{/if}
		{/snippet}
		<div class="flex flex-col gap-3">
			<div class="flex items-center gap-2">
				{#if job.status === 'running'}<Spinner size={14} class="text-primary-ink" />{/if}
				<span class="text-sm font-medium text-ink">{PHASE_LABELS[job.phase] ?? job.phase}</span>
				<Badge>{job.status}</Badge>
			</div>

			{#if job.status === 'running' && job.progress !== null}
				<ProgressBar label="Flashing" value={Math.round(job.progress * 100)} />
			{/if}

			{#if job.status === 'done'}
				<Alert tone="success">
					Flashed.
					{#if job.result?.board?.version?.firmware_version}
						The board reports firmware {job.result.board.version.firmware_version}.
					{/if}
					The machine is in standby: home it from the dashboard when you're ready.
				</Alert>
			{:else if job.status === 'failed'}
				<Alert tone="danger">{job.error ?? 'The flash failed.'}</Alert>
			{:else if job.status === 'cancelled'}
				<Alert tone="warning">{job.error ?? 'The flash was cancelled.'}</Alert>
			{/if}

			{#if job.log.length}
				<div class="max-h-48 overflow-y-auto rounded-control bg-well p-3">
					{#each job.log as line}
						<p class="font-mono text-sm leading-relaxed text-ink-muted">{line}</p>
					{/each}
				</div>
			{/if}
		</div>
	</Panel>
{/if}
