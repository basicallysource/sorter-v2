<script lang="ts">
	import { getApiBaseUrl } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';

	let installId = $state('');
	let submitting = $state(false);
	let error = $state<string | null>(null);
	let result = $state<{ deleted: number } | null>(null);

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (submitting) return;
		error = null;
		result = null;
		submitting = true;
		try {
			const res = await fetch(`${getApiBaseUrl()}/api/installs/forget`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ install_id: installId.trim() })
			});
			if (!res.ok) throw new Error(`Request failed (HTTP ${res.status})`);
			result = (await res.json()) as { deleted: number };
			installId = '';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Deletion failed';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Delete anonymous data - Hive</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="mx-auto flex min-h-[80vh] w-full max-w-xl flex-col justify-center gap-(--gap-panels)">
	<PageHeader
		title="Delete anonymous data"
		description="A Sorter sends an anonymous status ping (that it exists, its software version and rough usage counts) under a random install ID, never an account. Paste the ID here to erase everything held for it, for good."
	/>
	<Panel>
		<form onsubmit={handleSubmit} class="flex flex-col gap-4">
			<Field label="Install ID" for="installId" help="It is on the machine's telemetry page, at /telemetry.">
				<Input
					id="installId"
					bind:value={installId}
					placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
					required
					disabled={submitting}
					class="font-mono"
				/>
			</Field>
			{#if error}<Alert tone="danger">{error}</Alert>{/if}
			{#if result}
				<Alert tone="success" title="Done">
					{#if result.deleted > 0}
						Everything for that install ID is erased. A new ping from the machine starts a new record; set
						<code class="font-mono">SORTER_BASE_REPORTING_OFF=1</code> on it to stop them.
					{:else}
						Nothing was held for that install ID. It may be deleted already, or mistyped.
					{/if}
				</Alert>
			{/if}
			<div>
				<Button variant="danger" type="submit" disabled={!installId.trim()} loading={submitting}>Delete the data</Button>
			</div>
		</form>
	</Panel>
</div>
