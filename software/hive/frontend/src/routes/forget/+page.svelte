<script lang="ts">
	import { getApiBaseUrl } from '$lib/api';
	import { Button, Alert } from '$lib/components/primitives';

	let installId = $state('');
	let submitting = $state(false);
	let error = $state<string | null>(null);
	let result = $state<{ deleted: number } | null>(null);

	async function handleSubmit(e: Event) {
		e.preventDefault();
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
	<title>Delete anonymous data · Hive</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="mx-auto flex min-h-screen w-full max-w-xl flex-col justify-center gap-6 px-5 py-10">
	<div>
		<h1 class="text-2xl font-bold text-text">Delete anonymous data</h1>
		<p class="mt-2 text-sm text-text-muted">
			Sorter machines send an anonymous status ping (existence, software version, and coarse usage
			counts) tied to a random install ID — never an account. Paste that install ID below to
			permanently erase everything we hold for it. You can find the ID on your machine at
			<code class="bg-surface px-1">/telemetry</code>.
		</p>
	</div>

	<form onsubmit={handleSubmit} class="space-y-4 border border-border bg-surface p-6">
		<div>
			<label for="installId" class="mb-1 block text-sm font-medium text-text">Install ID</label>
			<input
				id="installId"
				type="text"
				bind:value={installId}
				placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
				required
				disabled={submitting}
				class="w-full border border-border px-3 py-2 font-mono text-sm text-text focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none disabled:opacity-60"
			/>
		</div>

		{#if error}
			<Alert variant="danger" title="Error">{error}</Alert>
		{/if}

		{#if result}
			<Alert variant="success" title="Done">
				{#if result.deleted > 0}
					Deleted. Everything for that install ID has been erased. New pings from that machine will
					start a fresh record — set <code>SORTER_BASE_REPORTING_OFF=1</code> on the machine to stop them.
				{:else}
					No data was found for that install ID. It may have already been deleted, or the ID may be
					mistyped.
				{/if}
			</Alert>
		{/if}

		<Button variant="danger" type="submit" disabled={submitting || !installId.trim()} loading={submitting}>
			Delete my data
		</Button>
	</form>
</div>
