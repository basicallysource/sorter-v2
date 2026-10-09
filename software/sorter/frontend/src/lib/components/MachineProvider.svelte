<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext, setMachineContext } from '$lib/machines/context';
	import type { MachineContext } from '$lib/machines/types';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { untrack, type Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	const manager = getMachinesContext();

	const ctx: MachineContext = {
		get machine() {
			return manager.selectedMachine;
		},
		get cameraHealth() {
			return manager.selectedMachine?.cameraHealth ?? new Map();
		}
	};

	setMachineContext(ctx);

	// Category names on piece cards and bins come from the cached profile, so it
	// follows the profile the machine reports, however that profile was changed.
	$effect(() => {
		const status = manager.selectedMachine?.sortingProfileStatus;
		const local = status?.local_profile ?? {};
		const sync = status?.sync_state ?? {};
		const key = [local.artifact_hash, sync.artifact_hash, sync.applied_at].find(
			(value): value is string => typeof value === 'string' && value.length > 0
		);
		if (!key) return;
		const baseUrl =
			machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase();
		untrack(() => sortingProfileStore.follow(key, baseUrl));
	});
</script>

{@render children()}
