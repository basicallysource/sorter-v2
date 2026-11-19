<!--
	Feed profiles: how the machine feeds one kind of piece (1x1 plates, a mixed
	lot). Each is a saved copy of the feeder's and the classification channel's
	tuning; picking one writes it back, and saving copies what runs now.
-->
<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Popover from '$lib/components/ui/Popover.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Input from '$lib/components/ui/Input.svelte';

	type Change = { section: string; key: string; profile: unknown; current: unknown };
	type FeedProfile = {
		id: string;
		label: string;
		description: string;
		saved_at: number | null;
		active: boolean;
		matches: boolean;
		changes: Change[];
	};
	type Listing = { active: string | null; profiles: FeedProfile[] };

	const manager = getMachinesContext();
	let open = $state(false);
	let listing = $state<Listing>({ active: null, profiles: [] });
	let busy = $state<string | null>(null);
	let error = $state<string | null>(null);
	let newName = $state('');

	const active = $derived(listing.profiles.find((p) => p.active) ?? null);

	function base(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? getBackendHttpBase();
	}

	async function call(path: string, init?: RequestInit): Promise<void> {
		error = null;
		const res = await fetch(`${base()}${path}`, {
			...init,
			headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
		});
		if (!res.ok) {
			const body = await res.json().catch(() => null);
			throw new Error(body?.detail ?? `${res.status}`);
		}
		listing = await res.json();
	}

	async function load() {
		try {
			await call('/api/feed-profiles');
		} catch (e) {
			error = `Could not load feed profiles: ${(e as Error).message}`;
		}
	}

	async function act(key: string, path: string, init?: RequestInit) {
		busy = key;
		try {
			await call(path, init);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = null;
		}
	}

	function apply(p: FeedProfile) {
		act(`apply:${p.id}`, `/api/feed-profiles/${encodeURIComponent(p.id)}/apply`, { method: 'POST' });
	}

	function saveOver(p: FeedProfile) {
		act(`save:${p.id}`, '/api/feed-profiles', {
			method: 'POST',
			body: JSON.stringify({ id: p.id, label: p.label, description: p.description })
		});
	}

	function remove(p: FeedProfile) {
		act(`delete:${p.id}`, `/api/feed-profiles/${encodeURIComponent(p.id)}`, { method: 'DELETE' });
	}

	async function saveNew(e: SubmitEvent) {
		e.preventDefault();
		if (!newName.trim()) return;
		await act('new', '/api/feed-profiles', { method: 'POST', body: JSON.stringify({ label: newName }) });
		if (!error) newName = '';
	}

	$effect(() => {
		if (manager.selectedMachineId) load();
	});
	$effect(() => {
		if (open) load();
	});
</script>

<Popover label="Feed profile" placement="bottom-end" width="22rem" padded={false} bind:open>
	{#snippet trigger(props)}
		<button
			{...props}
			type="button"
			disabled={!manager.selectedMachineId}
			title="Feed profile: how the machine feeds this kind of piece"
			class="flex h-(--size-control-sm) max-w-52 items-center gap-2 rounded-control border border-line-strong bg-field pr-2 pl-2.5 text-sm text-ink transition-colors hover:border-ink-faint disabled:pointer-events-none disabled:opacity-45"
		>
			<span class="shrink-0 text-ink-muted">Feed</span>
			<span class="truncate font-medium">{active ? active.label : 'Custom'}</span>
			{#if active && !active.matches}<span class="shrink-0 text-ink-muted">(changed)</span>{/if}
			<ChevronDown size={16} class="shrink-0 text-ink-muted" />
		</button>
	{/snippet}

	<div class="px-4 py-3">
		<p class="text-sm text-ink-muted">
			How C1 to C4 feed and handle one kind of piece. Picking one sets the feeder now and the
			classification channel at its next start.
		</p>
	</div>

	{#if error}
		<div class="px-4 pb-3"><Alert tone="danger">{error}</Alert></div>
	{/if}

	<div class="max-h-[60dvh] divide-y divide-line overflow-y-auto border-y border-line">
		{#if listing.profiles.length === 0}
			<p class="px-4 py-3 text-ink-muted">No feed profiles yet. Save what runs now below.</p>
		{/if}
		{#each listing.profiles as p (p.id)}
			<div class="px-4 py-2.5">
				<div class="flex items-center justify-between gap-2">
					<span class="min-w-0 truncate font-medium text-ink">{p.label}</span>
					{#if p.active && p.matches}
						<Badge tone="success">Active</Badge>
					{:else if p.active}
						<Badge tone="warning">Active, changed</Badge>
					{/if}
				</div>
				{#if p.description}<p class="mt-0.5 text-sm text-ink-muted">{p.description}</p>{/if}
				{#if !p.matches}
					<p class="mt-0.5 text-sm text-ink-muted">
						{p.changes.length} setting{p.changes.length === 1 ? '' : 's'} differ from what runs now
					</p>
				{/if}
				<div class="mt-2 flex gap-1.5">
					{#if !(p.active && p.matches)}
						<Button size="sm" variant="primary" loading={busy === `apply:${p.id}`} onclick={() => apply(p)}
							>Use</Button
						>
					{/if}
					{#if !p.matches}
						<Button size="sm" loading={busy === `save:${p.id}`} onclick={() => saveOver(p)}
							>Save what runs now</Button
						>
					{/if}
					<Button size="sm" variant="ghost" loading={busy === `delete:${p.id}`} onclick={() => remove(p)}
						>Delete</Button
					>
				</div>
			</div>
		{/each}
	</div>

	<form class="flex gap-2 px-4 py-3" onsubmit={saveNew}>
		<Input size="sm" bind:value={newName} placeholder="New profile from what runs now" />
		<Button size="sm" type="submit" loading={busy === 'new'} disabled={!newName.trim()}>Save</Button>
	</form>
</Popover>
