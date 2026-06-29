<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { cameras, type CameraInfo, type CameraStatus } from '$lib/station';
	import { ChevronLeft, ChevronRight, Check, X, EyeOff, Eye, RefreshCw } from 'lucide-svelte';

	const ROLE_LABELS: Record<string, string> = {
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		classification: 'Classification',
		carousel: 'Carousel'
	};

	let cams = $state<CameraInfo[]>([]);
	let status = $state<CameraStatus | null>(null);
	let current = $state(0); // index into the working-cameras list
	let error = $state<string | null>(null);
	let loading = $state(true);
	let saved = $state(false);

	let working = $derived(cams.filter((c) => c.working && !c.excluded));
	let activeCam = $derived(working[current]);

	async function load() {
		loading = true;
		try {
			const r = await cameras.begin();
			cams = r.cameras;
			status = r.status;
			error = null;
			if (current >= working.length) current = 0;
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	async function reprobe() {
		try {
			const r = await cameras.list();
			cams = r.cameras;
			status = r.status;
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function assign(role: string) {
		if (!activeCam) return;
		try {
			status = await cameras.assign(role, activeCam.index);
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function unassign(role: string) {
		try {
			status = await cameras.unassign(role);
		} catch (e) {
			error = (e as Error).message;
		}
	}

	// Which roles is the active camera currently assigned to?
	let activeRoles = $derived(
		status && activeCam
			? Object.entries(status.assigned).filter(([, idx]) => idx === activeCam.index).map(([r]) => r)
			: []
	);

	function prev() {
		if (working.length) current = (current - 1 + working.length) % working.length;
	}
	function next() {
		if (working.length) current = (current + 1) % working.length;
	}

	async function save() {
		try {
			await cameras.end(true);
			saved = true;
			goto('/setup');
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function cancel() {
		try {
			await cameras.end(false);
			saved = true;
		} catch {
			/* ignore */
		}
		goto('/setup');
	}

	onMount(load);
	onDestroy(() => {
		// Release the cameras if the user navigates away without saving.
		if (!saved) cameras.end(false).catch(() => {});
	});

	let allRequiredDone = $derived(status != null && status.missing_required.length === 0);
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mb-4 flex items-center justify-between">
		<h1 class="dark:text-text-dark text-2xl font-bold text-text">Assign Cameras</h1>
		<div class="flex gap-2">
			<button onclick={reprobe} class="dark:text-text-dark flex items-center gap-1 rounded px-3 py-2 text-sm text-text hover:bg-surface">
				<RefreshCw size={16} /> Re-scan
			</button>
			<button onclick={cancel} class="rounded px-3 py-2 text-sm text-text-muted hover:bg-surface">Cancel</button>
			<button onclick={save} disabled={!allRequiredDone}
				class="flex items-center gap-1 rounded bg-green-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
				<Check size={16} /> Save &amp; Finish
			</button>
		</div>
	</div>

	{#if error}
		<div class="mb-4 rounded bg-red-500/15 px-4 py-2 text-sm text-red-500">{error}</div>
	{/if}

	{#if loading}
		<div class="dark:text-text-muted-dark py-12 text-center text-text-muted">Scanning cameras…</div>
	{:else if working.length === 0}
		<div class="dark:text-text-muted-dark py-12 text-center text-text-muted">
			No working cameras found. Check USB connections and click Re-scan.
		</div>
	{:else}
		<div class="flex flex-col gap-6 lg:flex-row">
			<!-- Preview of the current camera -->
			<div class="flex-1">
				<div class="dark:bg-surface-dark relative overflow-hidden rounded-lg bg-black">
					{#if activeCam}
						{#key activeCam.index}
							<img src={cameras.streamUrl(activeCam.index)} alt="camera {activeCam.index}" class="mx-auto block max-h-[60vh] w-full object-contain" />
						{/key}
					{/if}
					<div class="absolute left-0 right-0 top-0 flex items-center justify-between bg-black/50 px-3 py-2 text-white">
						<button onclick={prev} class="p-1 hover:text-blue-300"><ChevronLeft size={22} /></button>
						<span class="text-sm">
							Camera {activeCam?.index} — {activeCam?.name}
							<span class="opacity-60">({current + 1}/{working.length})</span>
						</span>
						<button onclick={next} class="p-1 hover:text-blue-300"><ChevronRight size={22} /></button>
					</div>
				</div>

				<!-- Assign the current camera to roles -->
				<div class="mt-3">
					<div class="dark:text-text-muted-dark mb-2 text-sm text-text-muted">Assign this camera as:</div>
					<div class="flex flex-wrap gap-2">
						{#each Object.keys(ROLE_LABELS) as role}
							{@const isActive = activeRoles.includes(role)}
							<button onclick={() => (isActive ? unassign(role) : assign(role))}
								class="rounded px-3 py-1.5 text-sm font-medium transition-colors
									{isActive ? 'bg-blue-600 text-white' : 'dark:bg-surface-dark dark:text-text-dark bg-surface text-text hover:bg-blue-500/20'}">
								{ROLE_LABELS[role]}
							</button>
						{/each}
					</div>
				</div>
			</div>

			<!-- Assignment summary -->
			<div class="w-full lg:w-80">
				<div class="dark:bg-surface-dark rounded-lg bg-surface p-4">
					<h2 class="dark:text-text-dark mb-3 font-medium text-text">Assignments</h2>
					{#each (status?.required_roles ?? []) as role}
						{@const idx = status?.assigned[role]}
						<div class="mb-2 flex items-center justify-between">
							<span class="dark:text-text-dark text-sm text-text">{ROLE_LABELS[role] ?? role}<span class="text-red-500">*</span></span>
							{#if idx !== undefined}
								<span class="flex items-center gap-2 text-sm text-green-500">
									cam {idx}
									<button onclick={() => unassign(role)} class="text-text-muted hover:text-red-500"><X size={14} /></button>
								</span>
							{:else}
								<span class="text-sm text-text-muted">unassigned</span>
							{/if}
						</div>
					{/each}
					<hr class="dark:border-bg-dark my-3 border-bg" />
					{#each Object.keys(ROLE_LABELS).filter((r) => !(status?.required_roles ?? []).includes(r)) as role}
						{@const idx = status?.assigned[role]}
						<div class="mb-2 flex items-center justify-between">
							<span class="dark:text-text-muted-dark text-sm text-text-muted">{ROLE_LABELS[role]}</span>
							{#if idx !== undefined}
								<span class="flex items-center gap-2 text-sm text-green-500">cam {idx}
									<button onclick={() => unassign(role)} class="text-text-muted hover:text-red-500"><X size={14} /></button>
								</span>
							{:else}
								<span class="text-sm text-text-muted">—</span>
							{/if}
						</div>
					{/each}
					<p class="dark:text-text-muted-dark mt-3 text-xs text-text-muted">
						<span class="text-red-500">*</span> required before the sorter can run.
					</p>
				</div>

				<button onclick={() => activeCam && cameras.exclude(activeCam.index, true).then((s) => (status = s)).then(reprobe)}
					class="dark:text-text-muted-dark mt-3 flex w-full items-center justify-center gap-2 rounded px-3 py-2 text-sm text-text-muted hover:bg-surface">
					<EyeOff size={15} /> Exclude this camera from scans
				</button>
			</div>
		</div>
	{/if}
</div>
