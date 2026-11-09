<!--
	Linking this sorter to Hive: off to Hive to sign in and confirm the name,
	and back here, where the link is finished. Or skip it for now.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import { errorMessage } from '$lib/api/http';
	import { beginHiveLink, completeReturnedHiveLink, DEFAULT_HIVE_URL } from '$lib/hive/link-flow';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow, onnext }: { flow: SetupFlow; onnext: () => void } = $props();

	let hiveUrl = $state(DEFAULT_HIVE_URL);
	let connecting = $state(false);
	let error = $state<string | null>(null);
	let status = $state<string | null>(null);

	const machineName = $derived((flow.summary?.machine.nickname ?? '').trim());

	function connect() {
		const url = hiveUrl.trim() || DEFAULT_HIVE_URL;
		connecting = true;
		error = null;
		status = null;
		try {
			// No name yet means no suggestion: Hive rolls one rather than showing
			// the machine ID, which reads as a serial number in a list.
			beginHiveLink({
				hiveUrl: url,
				targetName: undefined,
				machineName: machineName || undefined,
				// Back to this step, where the returned link is finished.
				returnPath: window.location.pathname + window.location.search
			});
		} catch (e) {
			error = errorMessage(e, 'Hive could not be opened.');
			connecting = false;
		}
	}

	function skip() {
		flow.mark({ hiveSkipped: true });
		onnext();
	}

	onMount(() => {
		void (async () => {
			try {
				const result = await completeReturnedHiveLink(flow.base);
				if (!result.completed) return;
				status = result.message ?? 'Connected to Hive. Samples sync in the background.';
				await flow.reload();
			} catch (e) {
				error = errorMessage(e, 'The Hive link could not be finished.');
			} finally {
				connecting = false;
			}
		})();
	});
</script>

<div class="flex flex-col gap-(--gap-panels)">
	{#if flow.hive}
		<Alert tone="success" title="Connected to Hive">
			This sorter is linked to <span class="font-mono">{flow.hive.url}</span>. You can manage the link in
			Settings › Hive.
		</Alert>
	{:else}
		<Panel
			title="Link to Hive"
			description="Hive opens for you to sign in (or make an account) and confirm the machine's name, then brings you back here to finish. No password is kept on this sorter."
		>
			<div class="flex max-w-xl flex-col gap-4">
				<Field label="Hive server" for="setup-hive-url" help="The community platform, unless you run a Hive of your own.">
					<Input
						id="setup-hive-url"
						type="url"
						class="font-mono"
						bind:value={hiveUrl}
						placeholder={DEFAULT_HIVE_URL}
						disabled={connecting}
					/>
				</Field>
				<KeyValue items={[{ label: 'Machine name', value: machineName || 'Not named yet' }]} />
			</div>
			{#snippet footer()}
				<Button variant="ghost" disabled={connecting} onclick={skip}>Skip for now</Button>
				<Button variant="primary" icon={ExternalLink} loading={connecting} disabled={!hiveUrl.trim()} onclick={connect}>
					Continue on Hive
				</Button>
			{/snippet}
		</Panel>
	{/if}

	{#if error}
		<Alert tone="danger" title="The Hive link failed">{error}</Alert>
	{:else if status}
		<Alert tone="success">{status}</Alert>
	{/if}
</div>
