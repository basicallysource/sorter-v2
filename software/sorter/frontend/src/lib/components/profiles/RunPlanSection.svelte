<script lang="ts">
	import { Button } from '$lib/components/primitives';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { applyRunPlan, fetchRunPlan } from '$lib/sorting-profiles/api';
	import type { RunPlan, RunPlanRule } from '$lib/sorting-profiles/types';

	// refreshKey: bump after a profile apply so the panel reloads its plan.
	let { baseUrl, refreshKey = 0 }: { baseUrl: string; refreshKey?: number } = $props();

	let plan = $state<RunPlan | null>(null);
	let selected = $state<string[]>([]);
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);

	const capacity = $derived(plan?.capacity ?? { primary: 0, secondary: 0 });
	const planSelection = $derived(
		(plan?.primary ?? []).filter((rule) => rule.selected).map((rule) => rule.id)
	);
	const dirty = $derived(
		selected.length !== planSelection.length || selected.some((id) => !planSelection.includes(id))
	);
	const atCapacity = $derived(selected.length >= capacity.primary);

	async function load() {
		loading = true;
		try {
			plan = await fetchRunPlan(baseUrl);
			selected = (plan.primary ?? []).filter((rule) => rule.selected).map((rule) => rule.id);
			error = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load run plan';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void baseUrl;
		void refreshKey;
		void load();
	});

	function toggle(rule: RunPlanRule, checked: boolean) {
		selected = checked ? [...selected, rule.id] : selected.filter((id) => id !== rule.id);
	}

	async function apply() {
		saving = true;
		error = null;
		success = null;
		try {
			const result = await applyRunPlan(baseUrl, selected);
			plan = result;
			selected = result.primary.filter((rule) => rule.selected).map((rule) => rule.id);
			success = `Run planned: ${result.assigned_count} bin${result.assigned_count === 1 ? '' : 's'} assigned. Empty the bins before starting.`;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to apply run plan';
		} finally {
			saving = false;
		}
	}

	function label(rule: RunPlanRule): string {
		return rule.set_meta?.name || rule.name;
	}

	function binLabel(rule: RunPlanRule): string {
		if (!rule.bin) return 'no bin (passthrough)';
		return `L${rule.bin.layer_index + 1} · S${rule.bin.section_index + 1} · B${rule.bin.bin_index + 1}`;
	}
</script>

<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
	<h3 class="text-sm font-semibold tracking-wider text-text-muted uppercase">Lauf planen</h3>
	{#if plan}
		<div class="flex items-center gap-3 text-xs text-text-muted">
			<span>{capacity.primary} primary slots · {capacity.secondary} secondary slots</span>
			<span
				class="border px-1.5 py-0.5 font-medium tracking-wide uppercase {plan.planned
					? 'border-success/30 bg-success/10 text-success'
					: 'border-border bg-bg'}"
			>
				{plan.planned ? 'Planned' : 'Dynamic'}
			</span>
		</div>
	{/if}
</div>

<StatusBanner message={success ?? ''} variant="success" />
<StatusBanner message={error ?? ''} variant="error" />

<div class="border border-border bg-surface">
	{#if loading && !plan}
		<div class="px-4 py-6 text-sm text-text-muted">Loading run plan…</div>
	{:else if plan}
		<div class="grid gap-0 md:grid-cols-2">
			<div class="border-b border-border md:border-r md:border-b-0">
				<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-2 text-xs text-text-muted">
					<span class="font-semibold tracking-wide uppercase">Primary targets</span>
					<span>{selected.length} / {capacity.primary} selected</span>
				</div>
				{#if plan.primary.length === 0}
					<div class="px-4 py-4 text-sm text-text-muted">This profile has no primary targets.</div>
				{:else}
					<ul class="divide-y divide-border">
						{#each plan.primary as rule (rule.id)}
							{@const checked = selected.includes(rule.id)}
							<li class="flex items-center gap-3 px-4 py-2 text-sm">
								<input
									type="checkbox"
									class="setup-toggle"
									{checked}
									disabled={saving || (!checked && atCapacity)}
									onchange={(event) => toggle(rule, event.currentTarget.checked)}
									aria-label={`Include ${label(rule)} in this run`}
								/>
								<div class="min-w-0 flex-1">
									<div class="truncate font-medium text-text">{label(rule)}</div>
									<div class="flex flex-wrap gap-x-2 text-xs text-text-muted">
										{#if rule.set_num}<span class="font-mono">{rule.set_num}</span>{/if}
										{#if rule.set_meta?.name && rule.set_meta.name !== rule.name}<span>{rule.name}</span>{/if}
										{#if rule.set_instance_id}<span title={rule.set_instance_id}>instance</span>{/if}
									</div>
								</div>
								<span class="shrink-0 font-mono text-xs text-text-muted">{binLabel(rule)}</span>
							</li>
						{/each}
					</ul>
				{/if}
				<div class="flex items-center justify-end gap-2 border-t border-border px-4 py-2">
					<Button size="sm" variant="primary" disabled={!dirty || saving} loading={saving} onclick={apply}>
						Apply run plan
					</Button>
				</div>
			</div>
			<div>
				<div class="flex items-center justify-between border-b border-border bg-bg px-4 py-2 text-xs text-text-muted">
					<span class="font-semibold tracking-wide uppercase">Secondary targets</span>
					<span>{plan.secondary.filter((rule) => rule.bin).length} / {plan.secondary.length} with a bin</span>
				</div>
				{#if plan.secondary.length === 0}
					<div class="px-4 py-4 text-sm text-text-muted">This profile has no secondary rules.</div>
				{:else}
					<ul class="divide-y divide-border">
						{#each plan.secondary as rule (rule.id)}
							<li class="flex items-center gap-3 px-4 py-2 text-sm">
								<div class="min-w-0 flex-1 truncate text-text">{label(rule)}</div>
								<span class="shrink-0 font-mono text-xs text-text-muted">{binLabel(rule)}</span>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>
	{/if}
</div>
