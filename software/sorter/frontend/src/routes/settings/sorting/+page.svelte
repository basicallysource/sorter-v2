<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import RadioGroup from '$lib/components/ui/RadioGroup.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type Section = 'feeder' | 'classification_channel';
	type FieldMeta = { key: string; label: string; type: string; section?: string; description?: string };
	type Values = Record<Section, Record<string, unknown>>;
	type Profile = {
		id: string;
		label: string;
		description: string;
		preset: boolean;
		active: boolean;
		values: Values;
	};
	type Listing = {
		active: string;
		profiles: Profile[];
		base: Values;
		fields: Record<Section, FieldMeta[]>;
	};
	type Mode = { mode: 'part_and_color' | 'color_only'; assumed_part_id: string | null; assumed_part_name: string | null };

	const SECTIONS: { id: Section; label: string }[] = [
		{ id: 'feeder', label: 'Feeder (C1 to C3)' },
		{ id: 'classification_channel', label: 'Classification channel (C4)' }
	];

	let listing = $state<Listing | null>(null);
	let mode = $state<Mode | null>(null);
	let modeChoice = $state<Mode['mode']>('part_and_color');
	let partId = $state('');
	let partName = $state('');
	let error = $state<string | null>(null);
	let note = $state<string | null>(null);
	let busy = $state<string | null>(null);

	// The new-profile dialog.
	let creating = $state(false);
	let newLabel = $state('');
	let newDescription = $state('');
	let startFrom = $state('default');
	let draft = $state<Record<Section, Record<string, string>>>({ feeder: {}, classification_channel: {} });

	const base = (): string => getBackendHttpBase();

	async function call<T>(path: string, init?: RequestInit): Promise<T> {
		const res = await fetch(`${base()}${path}`, {
			...init,
			headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
		});
		if (!res.ok) {
			const body = await res.json().catch(() => null);
			throw new Error(body?.detail ?? `HTTP ${res.status}`);
		}
		return res.json();
	}

	async function load() {
		error = null;
		try {
			[listing, mode] = await Promise.all([
				call<Listing>('/api/sorting/feed-profiles'),
				call<Mode>('/api/sorting/mode')
			]);
			modeChoice = mode.mode;
			partId = mode.assumed_part_id ?? '3024';
			partName = mode.assumed_part_name ?? (mode.assumed_part_id ? '' : 'Plate 1 x 1');
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function run(key: string, fn: () => Promise<void>, done?: string) {
		busy = key;
		error = null;
		note = null;
		try {
			await fn();
			if (done) note = done;
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = null;
		}
	}

	function useProfile(p: Profile) {
		run(
			`use:${p.id}`,
			async () => {
				listing = await call<Listing>('/api/sorting/feed-profiles/active', {
					method: 'POST',
					body: JSON.stringify({ id: p.id })
				});
			},
			`${p.label} runs now. The feeder takes it within a second, the classification channel at its next home.`
		);
	}

	function deleteProfile(p: Profile) {
		run(`delete:${p.id}`, async () => {
			listing = await call<Listing>(`/api/sorting/feed-profiles/${encodeURIComponent(p.id)}`, {
				method: 'DELETE'
			});
		});
	}

	function saveMode() {
		run(
			'mode',
			async () => {
				mode = await call<Mode>('/api/sorting/mode', {
					method: 'POST',
					body: JSON.stringify({
						mode: modeChoice,
						assumed_part_id: modeChoice === 'color_only' ? partId.trim() : mode?.assumed_part_id ?? '',
						assumed_part_name: modeChoice === 'color_only' ? partName.trim() : mode?.assumed_part_name ?? ''
					})
				});
			},
			'Saved. It applies from the next piece.'
		);
	}

	function fieldMeta(section: Section, key: string): FieldMeta | undefined {
		return listing?.fields[section].find((f) => f.key === key);
	}

	function shown(value: unknown): string {
		if (typeof value === 'number') return String(Math.round(value * 1000) / 1000);
		return String(value);
	}

	function changes(p: Profile): { section: Section; key: string; label: string; from: unknown; to: unknown }[] {
		if (!listing) return [];
		return SECTIONS.flatMap(({ id }) =>
			Object.entries(p.values[id] ?? {}).map(([key, to]) => ({
				section: id,
				key,
				label: fieldMeta(id, key)?.label ?? key,
				from: listing!.base[id][key],
				to
			}))
		);
	}

	function openCreate() {
		newLabel = '';
		newDescription = '';
		startFrom = listing?.active ?? 'default';
		fillDraft();
		creating = true;
	}

	function fillDraft() {
		if (!listing) return;
		const from = listing.profiles.find((p) => p.id === startFrom);
		const next: Record<Section, Record<string, string>> = { feeder: {}, classification_channel: {} };
		for (const { id } of SECTIONS) {
			for (const f of listing.fields[id]) {
				const v = from?.values[id]?.[f.key] ?? listing.base[id][f.key];
				next[id][f.key] = v === undefined || v === null ? '' : String(v);
			}
		}
		draft = next;
	}

	function parse(f: FieldMeta, raw: string): unknown {
		if (f.type === 'bool') return raw === 'true';
		if (f.type === 'int') return Math.round(Number(raw));
		if (f.type === 'float') return Number(raw);
		return raw;
	}

	function draftChanges(): Values {
		const values: Values = { feeder: {}, classification_channel: {} };
		if (!listing) return values;
		for (const { id } of SECTIONS) {
			for (const f of listing.fields[id]) {
				const raw = draft[id][f.key];
				if (raw === undefined || raw === '') continue;
				const v = parse(f, raw);
				if (typeof v === 'number' && !Number.isFinite(v)) continue;
				if (v !== listing.base[id][f.key]) values[id][f.key] = v;
			}
		}
		return values;
	}

	const draftCount = $derived.by(() => {
		const v = draftChanges();
		return Object.keys(v.feeder).length + Object.keys(v.classification_channel).length;
	});

	function saveNew(e: SubmitEvent) {
		e.preventDefault();
		run(
			'create',
			async () => {
				listing = await call<Listing>('/api/sorting/feed-profiles', {
					method: 'POST',
					body: JSON.stringify({ label: newLabel, description: newDescription, values: draftChanges() })
				});
				creating = false;
			},
			`Saved ${newLabel}. Press Use to run it.`
		);
	}

	$effect(() => {
		load();
	});
</script>

<svelte:head><title>Sorter - Sorting</title></svelte:head>

<PageHeader
	title="Sorting"
	description="How the machine handles the lot it is given: how pieces are identified, and the feed profile for their size."
/>

{#if error}<Alert tone="danger">{error}</Alert>{/if}
{#if note}<Alert tone="success">{note}</Alert>{/if}

{#if !listing || !mode}
	<div class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} /> Loading</div>
{:else}
	<Panel
		title="Identification"
		description="Part and color asks the part model and the color model. Color only asks just the color model, for a lot of one kind of piece sorted by color: faster, and with no part model to get wrong."
	>
		<div class="flex flex-col gap-4">
			<RadioGroup
				name="sorting-mode"
				label="Identification"
				bind:value={modeChoice}
				options={[
					{ value: 'part_and_color', label: 'Part and color', help: 'The usual: both models.' },
					{
						value: 'color_only',
						label: 'Color only',
						help: 'Only the color model. Every piece is taken to be the part named below; leave it empty to name no part and route by color alone.'
					}
				]}
			/>
			{#if modeChoice === 'color_only'}
				<div class="grid gap-3 sm:grid-cols-2">
					<Field label="Part number" for="assumed-part" help="Empty: no part, sorted by color alone.">
						<Input id="assumed-part" bind:value={partId} placeholder="3024" />
					</Field>
					<Field label="Part name" for="assumed-name">
						<Input id="assumed-name" bind:value={partName} placeholder="Plate 1 x 1" />
					</Field>
				</div>
			{/if}
			<div>
				<Button variant="primary" loading={busy === 'mode'} onclick={saveMode}>Save</Button>
			</div>
		</div>
	</Panel>

	<Panel
		title="Feed profile"
		description="How C1 to C4 feed one size of piece. A profile changes only the settings it lists; everything else stays as the machine has it. Presets come with the software; make your own from any of them."
	>
		{#snippet actions()}
			<Button size="sm" onclick={openCreate}>New profile</Button>
		{/snippet}
		<div class="divide-y divide-line">
			{#each listing.profiles as p (p.id)}
				{@const list = changes(p)}
				<div class="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
					<div class="flex items-center justify-between gap-3">
						<div class="flex min-w-0 items-center gap-2">
							<span class="truncate font-medium text-ink">{p.label}</span>
							{#if p.preset}<Badge>Preset</Badge>{/if}
							{#if p.active}<Badge tone="success">Running</Badge>{/if}
						</div>
						<div class="flex shrink-0 gap-1.5">
							{#if !p.active}
								<Button size="sm" variant="primary" loading={busy === `use:${p.id}`} onclick={() => useProfile(p)}
									>Use</Button
								>
							{/if}
							{#if !p.preset}
								<Button size="sm" variant="ghost" loading={busy === `delete:${p.id}`} onclick={() => deleteProfile(p)}
									>Delete</Button
								>
							{/if}
						</div>
					</div>
					{#if p.description}<p class="text-sm text-ink-muted">{p.description}</p>{/if}
					{#if list.length}
						<table class="w-full text-sm">
							<tbody>
								{#each list as c (c.section + c.key)}
									<tr class="border-t border-line first:border-t-0">
										<td class="py-1 pr-3 text-ink-muted">{c.label}</td>
										<td class="num py-1 text-right whitespace-nowrap text-ink-muted">{shown(c.from)}</td>
										<td class="num py-1 pl-3 text-right whitespace-nowrap text-ink">{shown(c.to)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				</div>
			{/each}
		</div>
	</Panel>
{/if}

<Modal bind:open={creating} title="New feed profile" size="lg">
	{#if listing}
		<form id="new-feed-profile" class="flex flex-col gap-4" onsubmit={saveNew}>
			<div class="grid gap-3 sm:grid-cols-2">
				<Field label="Name" for="profile-name">
					<Input id="profile-name" bind:value={newLabel} placeholder="2x4 bricks" required />
				</Field>
				<Field label="Start from" for="profile-from">
					<Select
						id="profile-from"
						bind:value={startFrom}
						options={listing.profiles.map((p) => ({ value: p.id, label: p.label }))}
						onchange={() => fillDraft()}
					/>
				</Field>
			</div>
			<Field label="What it is for" for="profile-description">
				<Input id="profile-description" bind:value={newDescription} placeholder="Large bricks that roll" />
			</Field>
			<p class="text-sm text-ink-muted">
				{draftCount} setting{draftCount === 1 ? '' : 's'} differ from what the machine has; only those are saved.
			</p>
			{#each SECTIONS as s (s.id)}
				<details class="rounded-control border border-line">
					<summary class="cursor-pointer px-3 py-2 font-medium text-ink">{s.label}</summary>
					<div class="flex max-h-[45dvh] flex-col divide-y divide-line overflow-y-auto">
						{#each listing.fields[s.id] as f (f.key)}
							<label class="flex items-center justify-between gap-3 px-3 py-1.5" title={f.description ?? ''}>
								<span class="min-w-0 text-sm text-ink">{f.label}</span>
								{#if f.type === 'bool'}
									<select class="rounded-control border border-line-strong bg-field px-2 py-1 text-sm" bind:value={draft[s.id][f.key]}>
										<option value="true">On</option>
										<option value="false">Off</option>
									</select>
								{:else}
									<input
										class="num w-28 shrink-0 rounded-control border border-line-strong bg-field px-2 py-1 text-right text-sm"
										inputmode="decimal"
										bind:value={draft[s.id][f.key]}
									/>
								{/if}
							</label>
						{/each}
					</div>
				</details>
			{/each}
		</form>
	{/if}
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (creating = false)}>Cancel</Button>
		<Button variant="primary" type="submit" form="new-feed-profile" loading={busy === 'create'} disabled={!newLabel.trim()}
			>Save profile</Button
		>
	{/snippet}
</Modal>
