<script lang="ts">
	import { onMount } from 'svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';

	const machine = getMachineContext();

	let showSampleCapture = $state(false);
	let loading = $state(true);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? backendHttpBaseUrl;
	}

	async function loadConfig() {
		loading = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/dashboard-config`);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			showSampleCapture = Boolean(payload?.show_sample_capture);
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to load dashboard preferences.';
		} finally {
			loading = false;
		}
	}

	async function saveShowSampleCapture(next: boolean) {
		saving = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/dashboard-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ show_sample_capture: next })
			});
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			showSampleCapture = Boolean(payload?.show_sample_capture);
			statusMsg = 'Saved. Reload the dashboard to apply.';
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to save dashboard preferences.';
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		void loadConfig();
	});
</script>

<div class="flex flex-col gap-3">
	<label class="flex items-start gap-3 border border-border bg-bg px-3 py-2.5 text-sm text-text">
		<input
			type="checkbox"
			checked={showSampleCapture}
			disabled={loading || saving}
			onchange={(event) => void saveShowSampleCapture(event.currentTarget.checked)}
			class="mt-0.5 h-4 w-4 accent-sky-500"
		/>
		<span class="min-w-0">
			<span class="block text-sm font-medium text-text">Show Sample Capture panel</span>
			<span class="mt-0.5 block text-sm text-text-muted">
				When enabled, the Sample Capture controls appear in the dashboard sidebar.
				Used for training-sample collection drives — hidden by default during
				normal sorting.
			</span>
		</span>
	</label>

	{#if errorMsg}
		<div class="text-sm text-danger dark:text-red-400">{errorMsg}</div>
	{:else if statusMsg}
		<div class="text-sm text-text-muted">{statusMsg}</div>
	{/if}
</div>
