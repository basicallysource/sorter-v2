<script lang="ts">
	import Modal from './Modal.svelte';
	import { backendHttpBaseUrl } from '$lib/backend';
	import { Pencil } from 'lucide-svelte';

	let { open = $bindable(false) } = $props();

	type CameraInfo = { index: number; width: number; height: number };
	type Role = 'c_channel_2' | 'c_channel_3' | 'carousel';

	const roles: { key: Role; label: string }[] = [
		{ key: 'c_channel_2', label: 'C Channel 2' },
		{ key: 'c_channel_3', label: 'C Channel 3' },
		{ key: 'carousel', label: 'Carousel' }
	];

	let cameras = $state<CameraInfo[]>([]);
	let loading = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let successMsg = $state<string | null>(null);
	let editingRole = $state<Role | null>(null);
	let assignments = $state<Record<Role, number | null>>({
		c_channel_2: null,
		c_channel_3: null,
		carousel: null
	});

	async function loadConfig() {
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/config`);
			if (res.ok) {
				const cfg = await res.json();
				assignments.c_channel_2 = cfg.c_channel_2 ?? null;
				assignments.c_channel_3 = cfg.c_channel_3 ?? null;
				assignments.carousel = cfg.carousel ?? null;
			}
		} catch {
			// ignore
		}
	}

	async function scanCameras() {
		loading = true;
		error = null;
		try {
			await loadConfig();
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/list`);
			if (!res.ok) throw new Error(await res.text());
			cameras = await res.json();
		} catch (e: any) {
			error = e.message ?? 'Failed to scan cameras';
		} finally {
			loading = false;
		}
	}

	function selectCamera(role: Role, cameraIndex: number) {
		// Clear this camera from any other role
		for (const r of roles) {
			if (assignments[r.key] === cameraIndex && r.key !== role) {
				assignments[r.key] = null;
			}
		}
		assignments[role] = cameraIndex;
		editingRole = null;
		save();
	}

	function streamUrl(index: number): string {
		return `${backendHttpBaseUrl}/api/cameras/stream/${index}`;
	}

	let allAssigned = $derived(
		assignments.c_channel_2 !== null &&
			assignments.c_channel_3 !== null &&
			assignments.carousel !== null
	);

	async function save() {
		saving = true;
		error = null;
		successMsg = null;
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(assignments)
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			successMsg = data.message ?? 'Saved!';
		} catch (e: any) {
			error = e.message ?? 'Failed to save';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		if (open && cameras.length === 0 && !loading) {
			scanCameras();
		}
	});
</script>

<Modal bind:open title="Camera Setup">
	<div class="flex flex-col gap-3">
		{#if error}
			<div class="border border-red-400 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-600 dark:bg-red-900/20 dark:text-red-400">
				{error}
			</div>
		{/if}

		{#if successMsg}
			<div class="border border-green-400 bg-green-50 px-3 py-2 text-sm text-green-600 dark:border-green-600 dark:bg-green-900/20 dark:text-green-400">
				{successMsg}
			</div>
		{/if}

		<div class="grid grid-cols-3 gap-3">
			{#each roles as r}
				{@const assigned = assignments[r.key]}
				<div class="border border-border dark:border-border-dark">
					<!-- Role header -->
					<div class="flex items-center justify-between px-3 py-2 bg-surface dark:bg-surface-dark">
						<span class="text-sm font-medium text-text dark:text-text-dark">{r.label}</span>
						<div class="flex items-center gap-2">
							{#if assigned !== null}
								<span class="text-xs text-text-muted dark:text-text-muted-dark">Cam {assigned}</span>
							{:else}
								<span class="text-xs text-red-500">—</span>
							{/if}
							<button
								onclick={() => (editingRole = editingRole === r.key ? null : r.key)}
								class="p-1 text-text-muted hover:text-text dark:text-text-muted-dark dark:hover:text-text-dark transition-colors"
								title="Change camera"
							>
								<Pencil size={14} />
							</button>
						</div>
					</div>

					<!-- Assigned camera preview -->
					{#if assigned !== null && editingRole !== r.key}
						<div class="bg-black aspect-video">
							<img
								src={streamUrl(assigned)}
								alt="{r.label} - Camera {assigned}"
								class="w-full h-full object-contain"
							/>
						</div>
					{/if}

					<!-- Camera picker (expanded) -->
					{#if editingRole === r.key}
						{#if loading}
							<div class="py-6 text-center text-sm text-text-muted dark:text-text-muted-dark">
								Scanning...
							</div>
						{:else}
							<div class="flex flex-col gap-1 p-2 bg-bg dark:bg-bg-dark">
								{#each cameras as cam}
									{@const isSelected = assigned === cam.index}
									{@const usedByOther = !isSelected && roles.some((or) => or.key !== r.key && assignments[or.key] === cam.index)}
									<button
										onclick={() => selectCamera(r.key, cam.index)}
										disabled={usedByOther}
										class="relative cursor-pointer overflow-hidden border-2 transition-all {isSelected
											? 'border-blue-500'
											: usedByOther
												? 'border-border opacity-40 cursor-not-allowed dark:border-border-dark'
												: 'border-transparent hover:border-blue-300 dark:hover:border-blue-600'}"
									>
										<img
											src={streamUrl(cam.index)}
											alt="Camera {cam.index}"
											class="block w-full"
										/>
										<div class="absolute bottom-0 left-0 right-0 bg-black/70 px-1 py-0.5 text-[10px] text-white text-center">
											{cam.index}
										</div>
										{#if isSelected}
											<div class="absolute top-0 left-0 right-0 bg-blue-500/90 px-1 py-0.5 text-[10px] text-white text-center font-medium">
												Selected
											</div>
										{/if}
									</button>
								{/each}
							</div>
						{/if}
					{/if}
				</div>
			{/each}
		</div>
	</div>
</Modal>
