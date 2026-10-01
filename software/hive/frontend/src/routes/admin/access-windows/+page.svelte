<script lang="ts">
	import { sentence } from '$lib/text';
	import { auth } from '$lib/auth.svelte';
	import { api, type AccessWindow } from '$lib/api';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Select from '$lib/components/Select.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';

	let windows = $state<AccessWindow[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let savingKey = $state<string | null>(null);
	let flash = $state<string | null>(null);

	$effect(() => {
		if (!auth.isAdmin) {
			goto('/');
			return;
		}
		load();
	});

	async function load() {
		loading = true;
		error = null;
		try {
			const resp = await api.getAccessWindows();
			windows = resp.windows;
		} catch (e: any) {
			error = e.error || 'Failed to load access windows';
		} finally {
			loading = false;
		}
	}

	function keyOf(w: AccessWindow) {
		return `${w.role}/${w.entity}`;
	}

	async function save(w: AccessWindow) {
		savingKey = keyOf(w);
		error = null;
		flash = null;
		try {
			const resp = await api.updateAccessWindow(w.role, w.entity, {
				anchor: w.anchor,
				size: w.size,
				offset: w.offset
			});
			windows = resp.windows;
			flash = `Saved ${w.role} / ${entityLabel(w.entity)}.`;
		} catch (e: any) {
			error = e.error || 'Failed to save window';
		} finally {
			savingKey = null;
		}
	}

	function entityLabel(entity: string) {
		return entity === 'piece' ? 'Pieces' : 'Channel crops';
	}
</script>

<svelte:head>
	<title>Access windows - Hive</title>
</svelte:head>

<PageHeader title="Access windows" description="Admins see everything; this bounds everyone else." />

<div class="flex flex-col gap-(--gap-panels)">
	<Panel>
		<p class="max-w-3xl text-sm text-ink-muted">
			How much of the growing piece dataset each role can see and download: a run of rows in upload order.
			<strong class="font-medium text-ink">Oldest</strong> starts the run at the beginning of the dataset, so it stays on the
			same rows as new data arrives; meant for members. <strong class="font-medium text-ink">Newest</strong> starts it at the
			end, so it moves with new uploads; meant for reviewers. <strong class="font-medium text-ink">Size</strong> is how
			many rows it shows, and <strong class="font-medium text-ink">offset</strong> skips that many from its start.
		</p>
	</Panel>

	{#if error}<Alert tone="danger">{error}</Alert>{/if}
	{#if flash}<Alert tone="success">{flash}</Alert>{/if}

	{#if loading}
		<div class="flex justify-center py-12"><Spinner size={32} /></div>
	{:else}
		<Panel flush>
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr><th>Role</th><th>Data</th><th>Start at</th><th>Size</th><th>Offset</th><th>Source</th><th aria-label="Actions"></th></tr>
					</thead>
					<tbody>
						{#each windows as w (keyOf(w))}
							<tr>
								<td class="font-medium whitespace-nowrap">{sentence(w.role)}</td>
								<td class="whitespace-nowrap">{entityLabel(w.entity)}</td>
								<td>
									<Select
										class="w-44"
										size="sm"
										label="Start at"
										bind:value={w.anchor}
										options={[
											{ value: 'oldest', label: 'Oldest, stays put' },
											{ value: 'newest', label: 'Newest, moves on' }
										]}
									/>
								</td>
								<td><Input size="sm" type="number" class="w-28" min={0} bind:value={w.size} /></td>
								<td><Input size="sm" type="number" class="w-24" min={0} bind:value={w.offset} /></td>
								<td><Badge tone={w.source === 'override' ? 'info' : 'neutral'}>{sentence(w.source)}</Badge></td>
								<td class="text-right">
									<Button size="sm" loading={savingKey === keyOf(w)} onclick={() => save(w)}>Save</Button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Panel>
	{/if}
</div>
