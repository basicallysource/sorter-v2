<!--
	The machine filter of the review pages: one machine or several. A click on
	a machine adds or removes it; "All machines" clears the choice. Grouped by
	owner, the viewer's own first.
-->
<script lang="ts">
	import type { Machine } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import FilterGroup from './FilterGroup.svelte';
	import FilterOption from './FilterOption.svelte';

	let {
		machines,
		selected,
		onchange,
		storageKey = 'machine'
	}: {
		machines: Machine[];
		selected: string[];
		onchange: (ids: string[]) => void;
		storageKey?: string;
	} = $props();

	type Group = { key: string; label: string; machines: Machine[] };

	const groups = $derived.by<Group[]>(() => {
		const myId = auth.user?.id ?? null;
		const byOwner = new Map<string, Group>();
		for (const m of machines) {
			const ownerId = m.owner?.id ?? m.owner_id ?? 'unknown';
			const mine = myId !== null && ownerId === myId;
			const key = mine ? '__me' : ownerId;
			let group = byOwner.get(key);
			if (!group) {
				group = { key, label: mine ? 'Mine' : m.owner?.display_name?.trim() || 'Other machines', machines: [] };
				byOwner.set(key, group);
			}
			group.machines.push(m);
		}
		return [...byOwner.values()].sort((a, b) =>
			a.key === '__me' ? -1 : b.key === '__me' ? 1 : a.label.localeCompare(b.label)
		);
	});

	const chosen = $derived(new Set(selected));
	const activeLabel = $derived.by(() => {
		if (selected.length === 0) return null;
		const names = machines.filter((m) => chosen.has(String(m.id))).map((m) => m.name);
		if (names.length === 0) return `${selected.length} chosen`;
		return names.length <= 2 ? names.join(', ') : `${names.length} machines`;
	});

	function toggle(id: string) {
		onchange(chosen.has(id) ? selected.filter((s) => s !== id) : [...selected, id]);
	}
</script>

<FilterGroup title="Machine" {storageKey} active={selected.length > 0} {activeLabel}>
	<ul class="flex flex-col gap-px">
		<FilterOption label="All machines" on={selected.length === 0} onclick={() => onchange([])} />
		{#each groups as group (group.key)}
			{#if groups.length > 1}<li class="label px-2.5 pt-2 pb-1">{group.label}</li>{/if}
			{#each group.machines as m (m.id)}
				<FilterOption
					label={m.name}
					on={chosen.has(String(m.id))}
					onclick={() => toggle(String(m.id))}
					title={m.owner?.display_name ? `${m.owner.display_name}, ${m.name}` : m.name}
				/>
			{/each}
		{/each}
	</ul>
</FilterGroup>
