<script lang="ts">
	import type { SortingProfileRule } from '$lib/api';
	import ProfileRuleNode from './ProfileRuleNode.svelte';

	interface Props {
		rule: SortingProfileRule;
		depth?: number;
		index: number;
		siblingCount: number;
		selectedRuleId: string | null;
		onSelect: (ruleId: string) => void;
		onAddChild: (parentId: string) => void;
		onDeleteRule: (ruleId: string) => void;
		onMoveRule: (ruleId: string, direction: -1 | 1) => void;
		onUpdateRule: (ruleId: string, patch: Partial<SortingProfileRule>) => void;
		onAddCondition: (ruleId: string) => void;
		onUpdateCondition: (ruleId: string, conditionId: string, patch: Record<string, unknown>) => void;
		onDeleteCondition: (ruleId: string, conditionId: string) => void;
	}

	let {
		rule,
		depth = 0,
		index,
		siblingCount,
		selectedRuleId,
		onSelect,
		onAddChild,
		onDeleteRule,
		onMoveRule,
		onUpdateRule,
		onAddCondition,
		onUpdateCondition,
		onDeleteCondition
	}: Props = $props();

	const fieldOptions = [
		'name',
		'part_num',
		'category_id',
		'category_name',
		'color_id',
		'year_from',
		'year_to',
		'bricklink_id',
		'bricklink_item_count',
		'bricklink_primary_item_no',
		'bl_price_min',
		'bl_price_max',
		'bl_price_avg',
		'bl_price_qty_avg',
		'bl_price_lots',
		'bl_price_qty',
		'bl_catalog_name',
		'bl_catalog_category_id',
		'bl_category_id',
		'bl_category_name',
		'bl_catalog_year_released',
		'bl_catalog_weight',
		'bl_catalog_dim_x',
		'bl_catalog_dim_y',
		'bl_catalog_dim_z',
		'bl_catalog_is_obsolete'
	];

	const opOptionsByField: Record<string, string[]> = {
		name: ['contains', 'regex'],
		part_num: ['eq', 'neq', 'in'],
		category_id: ['eq', 'neq', 'in'],
		category_name: ['contains', 'regex'],
		color_id: ['eq', 'neq', 'in'],
		year_from: ['eq', 'neq', 'gte', 'lte'],
		year_to: ['eq', 'neq', 'gte', 'lte'],
		bricklink_id: ['eq', 'neq', 'in'],
		bricklink_item_count: ['eq', 'neq', 'gte', 'lte'],
		bricklink_primary_item_no: ['eq', 'neq', 'contains', 'regex'],
		bl_price_min: ['eq', 'neq', 'gte', 'lte'],
		bl_price_max: ['eq', 'neq', 'gte', 'lte'],
		bl_price_avg: ['eq', 'neq', 'gte', 'lte'],
		bl_price_qty_avg: ['eq', 'neq', 'gte', 'lte'],
		bl_price_lots: ['eq', 'neq', 'gte', 'lte'],
		bl_price_qty: ['eq', 'neq', 'gte', 'lte'],
		bl_catalog_name: ['contains', 'regex'],
		bl_catalog_category_id: ['eq', 'neq', 'in'],
		bl_category_id: ['eq', 'neq', 'in'],
		bl_category_name: ['contains', 'regex'],
		bl_catalog_year_released: ['eq', 'neq', 'gte', 'lte'],
		bl_catalog_weight: ['eq', 'neq', 'gte', 'lte'],
		bl_catalog_dim_x: ['eq', 'neq', 'gte', 'lte'],
		bl_catalog_dim_y: ['eq', 'neq', 'gte', 'lte'],
		bl_catalog_dim_z: ['eq', 'neq', 'gte', 'lte'],
		bl_catalog_is_obsolete: ['eq', 'neq']
	};

	function formatConditionValue(value: unknown): string {
		if (Array.isArray(value)) return JSON.stringify(value);
		if (typeof value === 'number') return String(value);
		if (typeof value === 'string') return value;
		if (value === null || value === undefined) return '';
		return JSON.stringify(value);
	}

	function parseConditionValue(raw: string): unknown {
		const trimmed = raw.trim();
		if (!trimmed) return '';
		if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
			try {
				return JSON.parse(trimmed);
			} catch {
				return trimmed;
			}
		}
		if (trimmed === 'true') return true;
		if (trimmed === 'false') return false;
		if (!Number.isNaN(Number(trimmed)) && trimmed !== '') {
			return Number(trimmed);
		}
		return trimmed;
	}
</script>

<div class="space-y-3 border border-border bg-white p-3" style={`margin-left: ${depth * 16}px`}>
	<div class="flex flex-wrap items-start justify-between gap-2">
		<div class="flex min-w-0 flex-1 flex-col gap-2">
			<div class="flex flex-wrap items-center gap-2">
				<input
					type="text"
					value={rule.name}
					oninput={(event) =>
						onUpdateRule(rule.id, { name: (event.currentTarget as HTMLInputElement).value })}
					class="min-w-[14rem] flex-1 border border-border px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
				<select
					value={rule.match_mode}
					onchange={(event) =>
						onUpdateRule(rule.id, { match_mode: (event.currentTarget as HTMLSelectElement).value })}
					class="border border-border px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				>
					<option value="all">All</option>
					<option value="any">Any</option>
				</select>
				<label class="flex items-center gap-2 text-xs text-text-muted">
					<input
						type="checkbox"
						checked={rule.disabled}
						onchange={(event) =>
							onUpdateRule(rule.id, { disabled: (event.currentTarget as HTMLInputElement).checked })}
					/>
					Disabled
				</label>
			</div>
			<div class="text-xs text-text-muted">Rule ID: <span class="font-mono">{rule.id}</span></div>
		</div>
		<div class="flex flex-wrap gap-2">
			<button
				type="button"
				onclick={() => onSelect(rule.id)}
				class="border border-border px-2 py-1 text-xs font-medium {selectedRuleId === rule.id ? 'bg-primary-light text-primary' : 'text-text hover:bg-bg'}"
			>
				{selectedRuleId === rule.id ? 'Selected' : 'Select'}
			</button>
			<button
				type="button"
				onclick={() => onMoveRule(rule.id, -1)}
				disabled={index === 0}
				class="border border-border px-2 py-1 text-xs font-medium text-text hover:bg-bg disabled:opacity-50"
			>
				Up
			</button>
			<button
				type="button"
				onclick={() => onMoveRule(rule.id, 1)}
				disabled={index >= siblingCount - 1}
				class="border border-border px-2 py-1 text-xs font-medium text-text hover:bg-bg disabled:opacity-50"
			>
				Down
			</button>
			<button
				type="button"
				onclick={() => onAddChild(rule.id)}
				class="border border-border px-2 py-1 text-xs font-medium text-text hover:bg-bg"
			>
				Add Child
			</button>
			<button
				type="button"
				onclick={() => onDeleteRule(rule.id)}
				class="border border-primary/30 px-2 py-1 text-xs font-medium text-primary hover:bg-primary-light"
			>
				Delete
			</button>
		</div>
	</div>

	<div class="space-y-2 bg-bg p-3">
		<div class="flex items-center justify-between">
			<h4 class="text-sm font-medium text-text">Conditions</h4>
			<button
				type="button"
				onclick={() => onAddCondition(rule.id)}
				class="border border-border bg-white px-2 py-1 text-xs font-medium text-text hover:bg-bg"
			>
				Add Condition
			</button>
		</div>
		{#if rule.conditions.length === 0}
			<p class="text-xs text-text-muted">No conditions yet. This rule currently matches everything in its scope.</p>
		{:else}
			<div class="space-y-2">
				{#each rule.conditions as condition}
					<div class="grid gap-2 md:grid-cols-[1.2fr,0.8fr,1.2fr,auto]">
						<select
							value={condition.field}
							onchange={(event) =>
								onUpdateCondition(rule.id, condition.id, { field: (event.currentTarget as HTMLSelectElement).value })}
							class="border border-border bg-white px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						>
							{#each fieldOptions as field}
								<option value={field}>{field}</option>
							{/each}
						</select>
						<select
							value={condition.op}
							onchange={(event) =>
								onUpdateCondition(rule.id, condition.id, { op: (event.currentTarget as HTMLSelectElement).value })}
							class="border border-border bg-white px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						>
							{#each (opOptionsByField[condition.field] ?? ['eq', 'neq', 'in', 'contains', 'regex', 'gte', 'lte']) as op}
								<option value={op}>{op}</option>
							{/each}
						</select>
						<input
							type="text"
							value={formatConditionValue(condition.value)}
							onchange={(event) =>
								onUpdateCondition(rule.id, condition.id, { value: parseConditionValue((event.currentTarget as HTMLInputElement).value) })}
							class="border border-border bg-white px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						/>
						<button
							type="button"
							onclick={() => onDeleteCondition(rule.id, condition.id)}
							class="border border-primary/30 bg-white px-2 py-1.5 text-xs font-medium text-primary hover:bg-primary-light"
						>
							Remove
						</button>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	{#if rule.children.length > 0}
		<div class="space-y-3">
			{#each rule.children as child, childIndex (child.id)}
				<ProfileRuleNode
					rule={child}
					depth={depth + 1}
					index={childIndex}
					siblingCount={rule.children.length}
					{selectedRuleId}
					{onSelect}
					{onAddChild}
					{onDeleteRule}
					{onMoveRule}
					{onUpdateRule}
					{onAddCondition}
					{onUpdateCondition}
					{onDeleteCondition}
				/>
			{/each}
		</div>
	{/if}
</div>
