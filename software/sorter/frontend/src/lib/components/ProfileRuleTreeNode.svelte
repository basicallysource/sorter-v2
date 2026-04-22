<script lang="ts">
	import ProfileRuleTreeNode from '$lib/components/ProfileRuleTreeNode.svelte';

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
		depth?: number;
	}

	let { rule, depth = 0 }: Props = $props();

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

<div class="space-y-3 border border-border bg-surface p-3" style={`margin-left: ${Math.min(depth, 5) * 16}px`}>
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<div class="flex flex-wrap items-center gap-2">
				<h4 class="text-sm font-semibold text-text">{rule.name}</h4>
				<span class="border border-border bg-bg px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-text-muted">
					{ruleTypeLabel(rule)}
				</span>
				<span class="border border-border bg-bg px-1.5 py-0.5 text-xs font-medium text-text-muted">
					{rule.match_mode === 'any' ? 'Any condition' : 'All conditions'}
				</span>
				{#if rule.disabled}
					<span class="border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
						Disabled
					</span>
				{/if}
			</div>
			<div class="mt-1 text-sm text-text-muted">
				<span class="font-mono">{rule.id}</span>
			</div>
		</div>
	</div>

	{#if rule.rule_type === 'set'}
		<div class="flex flex-col gap-3 border border-border bg-bg/40 p-3 sm:flex-row sm:items-start">
			{#if rule.set_meta?.img_url}
				<img
					src={rule.set_meta.img_url}
					alt={rule.set_meta?.name ?? rule.name}
					class="h-20 w-20 shrink-0 border border-border bg-bg object-contain"
				/>
			{/if}
			<div class="min-w-0 flex-1 space-y-1.5">
				<div class="text-xs font-semibold uppercase tracking-wide text-text-muted">
					{sourceLabel(rule)}
				</div>
				{#if setMetaBits(rule).length > 0}
					<div class="flex flex-wrap gap-1.5">
						{#each setMetaBits(rule) as bit}
							<span class="border border-border bg-surface px-2 py-1 text-xs text-text-muted">{bit}</span>
						{/each}
					</div>
				{/if}
				{#if rule.custom_parts && rule.custom_parts.length > 0}
					<div>
						<div class="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
							Custom parts
						</div>
						<div class="space-y-1">
							{#each rule.custom_parts as part}
								<div class="text-xs text-text">{customPartSummary(part)}</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<div class="space-y-2">
		<div class="text-xs font-semibold uppercase tracking-wide text-text-muted">Conditions</div>
		{#if rule.conditions.length === 0}
			<div class="text-xs text-text-muted">
				{#if rule.rule_type === 'set'}
					Set rules match the compiled set inventory directly.
				{:else}
					No conditions. This rule currently matches everything in its scope.
				{/if}
			</div>
		{:else}
			<div class="space-y-2">
				{#each rule.conditions as condition}
					<div class="grid gap-2 border border-border bg-bg/40 px-3 py-2 text-xs md:grid-cols-[1fr,auto,1fr]">
						<div class="font-mono text-text">{condition.field}</div>
						<div class="text-text-muted">{condition.op}</div>
						<div class="break-all text-text">{formatConditionValue(condition.value)}</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	{#if rule.children.length > 0}
		<div class="space-y-3">
			<div class="text-xs font-semibold uppercase tracking-wide text-text-muted">
				Children ({rule.children.length})
			</div>
			{#each rule.children as child (child.id)}
				<ProfileRuleTreeNode rule={child} depth={depth + 1} />
			{/each}
		</div>
	{/if}
</div>
