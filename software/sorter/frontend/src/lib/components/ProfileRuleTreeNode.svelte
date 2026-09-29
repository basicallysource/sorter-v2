<script lang="ts">
	import ProfileRuleTreeNode from '$lib/components/ProfileRuleTreeNode.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';

	type SortingProfileCondition = {
		id: string;
		field: string;
		op: string;
		value: unknown;
	};

	type SortingProfileCustomPart = {
		part_num: string;
		color_id?: number | null;
		quantity?: number | null;
		part_name?: string | null;
		color_name?: string | null;
	};

	type SortingProfileRule = {
		id: string;
		rule_type: string;
		name: string;
		match_mode: string;
		conditions: SortingProfileCondition[];
		children: SortingProfileRule[];
		disabled: boolean;
		set_source?: string | null;
		set_num?: string | null;
		include_spares?: boolean;
		set_meta?: {
			name?: string | null;
			year?: number | null;
			img_url?: string | null;
			num_parts?: number | null;
		} | null;
		custom_parts?: SortingProfileCustomPart[];
	};

	interface Props {
		rule: SortingProfileRule;
	}

	let { rule }: Props = $props();

	function formatConditionValue(value: unknown): string {
		if (typeof value === 'string') return value;
		if (typeof value === 'number' || typeof value === 'boolean') return String(value);
		if (value === null || value === undefined) return '';
		try {
			return JSON.stringify(value);
		} catch {
			return String(value);
		}
	}

	function ruleTypeLabel(currentRule: SortingProfileRule): string {
		return currentRule.rule_type === 'set' ? 'Set rule' : 'Filter rule';
	}

	function sourceLabel(currentRule: SortingProfileRule): string | null {
		if (currentRule.rule_type !== 'set') return null;
		if (currentRule.set_source === 'custom') return 'Custom inventory';
		if (currentRule.set_source === 'rebrickable') return 'Official set';
		return 'Set';
	}

	function setMetaBits(currentRule: SortingProfileRule): string[] {
		const bits: string[] = [];
		if (currentRule.set_num) bits.push(currentRule.set_num);
		if (currentRule.set_meta?.year != null) bits.push(String(currentRule.set_meta.year));
		if (currentRule.set_meta?.num_parts != null) {
			bits.push(`${currentRule.set_meta.num_parts.toLocaleString()} parts`);
		}
		if (currentRule.include_spares) bits.push('Includes spares');
		return bits;
	}

	function customPartSummary(part: SortingProfileCustomPart): string {
		const name = part.part_name?.trim() || part.part_num;
		const color = part.color_name?.trim()
			? part.color_name.trim()
			: part.color_id === -1
				? 'Any color'
				: null;
		const pieces = `${Number(part.quantity ?? 0).toLocaleString()}x`;
		return color ? `${pieces} ${name} (${color})` : `${pieces} ${name}`;
	}
</script>

<!-- One rule of a profile. Its children sit under it, joined by a line down the left. -->
<div class="flex flex-col gap-3">
	<div>
		<div class="flex flex-wrap items-center gap-2">
			<h4 class="text-sm font-semibold text-ink">{rule.name}</h4>
			<Badge>{ruleTypeLabel(rule)}</Badge>
			<Badge>{rule.match_mode === 'any' ? 'Any condition' : 'All conditions'}</Badge>
			{#if rule.disabled}<Badge tone="warning">Disabled</Badge>{/if}
		</div>
		<div class="mt-1 text-sm text-ink-muted"><span class="font-mono">{rule.id}</span></div>
	</div>

	{#if rule.rule_type === 'set'}
		<div class="flex flex-col gap-3 rounded-control bg-well p-3 sm:flex-row sm:items-start">
			{#if rule.set_meta?.img_url}
				<img
					src={rule.set_meta.img_url}
					alt={rule.set_meta?.name ?? rule.name}
					class="size-20 shrink-0 rounded-item bg-surface object-contain"
				/>
			{/if}
			<div class="min-w-0 flex-1 space-y-2">
				<div class="label">{sourceLabel(rule)}</div>
				{#if setMetaBits(rule).length > 0}
					<div class="flex flex-wrap gap-1.5">
						{#each setMetaBits(rule) as bit}<Badge>{bit}</Badge>{/each}
					</div>
				{/if}
				{#if rule.custom_parts && rule.custom_parts.length > 0}
					<div>
						<div class="label mb-1">Custom parts</div>
						<ul class="space-y-0.5 text-sm text-ink">
							{#each rule.custom_parts as part}<li>{customPartSummary(part)}</li>{/each}
						</ul>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	{#if rule.conditions.length === 0}
		<p class="text-sm text-ink-muted">
			{#if rule.rule_type === 'set'}
				Set rules match the compiled set inventory directly.
			{:else}
				No conditions. This rule currently matches everything in its scope.
			{/if}
		</p>
	{:else}
		<div class="overflow-x-auto rounded-control">
			<table class="data-table">
				<thead>
					<tr><th>Field</th><th>Operator</th><th>Value</th></tr>
				</thead>
				<tbody>
					{#each rule.conditions as condition}
						<tr>
							<td class="font-mono">{condition.field}</td>
							<td class="text-ink-muted">{condition.op}</td>
							<td class="break-all">{formatConditionValue(condition.value)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if rule.children.length > 0}
		<div class="ml-1 flex flex-col gap-5 border-l border-line pl-4">
			<div class="label">Children ({rule.children.length})</div>
			{#each rule.children as child (child.id)}
				<ProfileRuleTreeNode rule={child} />
			{/each}
		</div>
	{/if}
</div>
