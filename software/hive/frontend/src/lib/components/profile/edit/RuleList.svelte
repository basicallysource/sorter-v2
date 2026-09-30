<!--
	The profile's bins in the order a piece meets them: one compact row for each
	rule, then the last row, "Everything else", which is what no rule takes.
	A piece goes to the first rule that takes it, so the order is the point: rows
	are dragged to reorder them, and from a keyboard Alt with the arrow keys (or
	each row's move buttons) does the same. The arrow keys alone walk the rows.
-->
<script lang="ts">
	import { tick } from 'svelte';
	import Boxes from '@lucide/svelte/icons/boxes';
	import type { ProfileBin } from '$lib/api';
	import RuleRow, { type RowMark } from './RuleRow.svelte';
	import { REST_ID, type Rule } from './rules';

	let {
		rules,
		bins,
		marks,
		selectedId,
		restName,
		restMeta,
		onselect,
		onmove,
		onreorder,
		ontoggle,
		onduplicate,
		ondelete
	}: {
		rules: Rule[];
		// The live preview's bins, by rule ID.
		bins: Record<string, ProfileBin>;
		marks: Record<string, RowMark>;
		// A rule's ID, or REST_ID for the last row.
		selectedId: string | null;
		restName: string;
		restMeta: string | null;
		onselect: (id: string) => void;
		onmove: (id: string, delta: -1 | 1) => void;
		// Put the rule where a drop at this slot means (0 is before the first rule).
		onreorder: (id: string, slot: number) => void;
		ontoggle: (id: string) => void;
		onduplicate: (id: string) => void;
		ondelete: (id: string) => void;
	} = $props();

	let list = $state<HTMLElement | undefined>();
	let dragId = $state<string | null>(null);
	let slot = $state<number | null>(null);

	const dragIndex = $derived(dragId === null ? -1 : rules.findIndex((rule) => rule.id === dragId));
	// A drop next to the rule itself changes nothing, so it shows no line.
	const target = $derived(slot !== null && slot !== dragIndex && slot !== dragIndex + 1 ? slot : null);

	function start(event: DragEvent, id: string) {
		dragId = id;
		event.dataTransfer?.setData('text/plain', id);
		if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
	}

	function over(event: DragEvent, index: number) {
		if (dragId === null) return;
		event.preventDefault();
		if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		slot = index + (event.clientY > box.top + box.height / 2 ? 1 : 0);
	}

	function drop(event: DragEvent) {
		event.preventDefault();
		if (dragId !== null && target !== null) onreorder(dragId, target);
		end();
	}

	function end() {
		dragId = null;
		slot = null;
	}

	function pick(id: string): HTMLElement | null {
		return list?.querySelector<HTMLElement>(`li[data-rule-id="${id}"] > button`) ?? null;
	}

	async function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
		const row = (event.target as HTMLElement).closest<HTMLElement>('li[data-rule-id]');
		if (!row || event.target !== row.querySelector(':scope > button')) return;
		event.preventDefault();
		const id = row.dataset.ruleId as string;
		const delta = event.key === 'ArrowUp' ? -1 : 1;
		if (event.altKey) {
			onmove(id, delta);
			await tick();
			pick(id)?.focus();
			return;
		}
		const index = rules.findIndex((rule) => rule.id === id);
		const next = rules[index + delta];
		if (next) pick(next.id)?.focus();
		else if (delta > 0) list?.querySelector<HTMLElement>('li[data-rest] > button')?.focus();
	}

	// A rule just added or chosen elsewhere comes into view.
	$effect(() => {
		const id = selectedId;
		if (!id || !list) return;
		void tick().then(() => list?.querySelector(`[data-rule-id="${id}"], [data-rest]`)?.scrollIntoView({ block: 'nearest' }));
	});
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<ul bind:this={list} class="divide-y divide-line" {onkeydown}>
	{#each rules as rule, index (rule.id)}
		<RuleRow
			{rule}
			bin={bins[rule.id]}
			number={index + 1}
			selected={selectedId === rule.id}
			mark={marks[rule.id] ?? null}
			first={index === 0}
			last={index === rules.length - 1}
			dropping={target === index ? 'before' : target === rules.length && index === rules.length - 1 ? 'after' : null}
			onselect={() => onselect(rule.id)}
			onmove={(delta) => onmove(rule.id, delta)}
			ontoggle={() => ontoggle(rule.id)}
			onduplicate={() => onduplicate(rule.id)}
			ondelete={() => ondelete(rule.id)}
			ondragstart={(event) => start(event, rule.id)}
			ondragend={end}
			ondragover={(event) => over(event, index)}
			ondrop={drop}
		/>
	{/each}
	<li data-rest class="relative isolate {selectedId === REST_ID ? 'bg-primary-soft' : ''}">
		<button
			type="button"
			aria-label={restName}
			aria-current={selectedId === REST_ID ? 'true' : undefined}
			onclick={() => onselect(REST_ID)}
			class="absolute inset-0 transition-colors hover:bg-hover active:bg-pressed"
		></button>
		<div class="pointer-events-none relative flex items-center gap-2 py-2 pr-3 pl-2">
			<span class="size-4 shrink-0"></span>
			<span class="w-5 shrink-0"></span>
			<span aria-hidden="true" class="flex size-10 shrink-0 items-center justify-center rounded-control bg-hover text-ink-faint">
				<Boxes size={18} />
			</span>
			<div class="min-w-0 flex-1">
				<div class="truncate text-sm font-medium text-ink">{restName}</div>
				{#if restMeta}<div class="truncate text-sm text-ink-muted">{restMeta}</div>{/if}
			</div>
		</div>
	</li>
</ul>
