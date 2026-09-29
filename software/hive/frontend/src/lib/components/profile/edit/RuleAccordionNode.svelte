<script lang="ts">
	import type { CustomSetPart, ProfileCatalogSearchResult, SortingProfileRule } from '$lib/api';
	import PartSearch from '$lib/components/profile/PartSearch.svelte';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import Self from './RuleAccordionNode.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Input from '$lib/components/Input.svelte';
	import Select from '$lib/components/Select.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import Switch from '$lib/components/Switch.svelte';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Plus from '@lucide/svelte/icons/plus';
	import Replace from '@lucide/svelte/icons/replace';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Upload from '@lucide/svelte/icons/upload';
	import X from '@lucide/svelte/icons/x';

	type RulePreviewResult = {
		total: number;
		sample: Array<Record<string, unknown>>;
		offset: number;
		limit: number;
	};

	interface Props {
		rule: SortingProfileRule;
		depth: number;
		isPreview: boolean;
		expandedNodes: Set<string>;
		selectedRuleId: string | null;
		rulePreview: RulePreviewResult | null;
		rulePreviewLoading: boolean;
		rulePreviewExpanded: boolean;
		catalogColorsLoading: boolean;
		addingPartForRule: string | null;
		changingSetForRule: string | null;
		importingCsvForRule: string | null;
		customSetImportStatus: Record<string, { tone: 'success' | 'error'; text: string }>;
		fieldOptions: string[];
		opOptionsByField: Record<string, string[]>;
		opLabels: Record<string, string>;
		liveRuleForRender: (rule: SortingProfileRule) => SortingProfileRule;
		isCustomSetRule: (rule: SortingProfileRule) => boolean;
		conditionSummary: (rule: SortingProfileRule) => string;
		customSetPartsLabel: (rule: SortingProfileRule) => string;
		normalizeCustomColorId: (colorId: number | string | null | undefined) => number;
		colorLabel: (colorId: number | string | null | undefined, fallback?: string | null) => string;
		customPartColorLabel: (part: CustomSetPart, colorId: number | string | null | undefined) => string;
		customPartColorOptions: (part: CustomSetPart) => Array<{ value: number; label: string }>;
		formatConditionValue: (value: unknown) => string;
		parseConditionValue: (raw: string) => unknown;
		onToggleNode: (id: string) => void;
		onSelectRule: (id: string) => void;
		onMoveRule: (id: string, direction: -1 | 1) => void;
		onDeleteRule: (id: string) => void;
		onUpdateRule: (id: string, patch: Partial<SortingProfileRule>) => void;
		onAddRule: (parentId?: string) => void;
		onAddCondition: (ruleId: string) => void;
		onUpdateCondition: (ruleId: string, conditionId: string, patch: Record<string, unknown>) => void;
		onDeleteCondition: (ruleId: string, conditionId: string) => void;
		onUpdateCustomSetName: (ruleId: string, name: string) => void;
		onOpenBrickLinkCsvImport: (ruleId: string) => void;
		onEnsureCatalogColorsLoaded: () => void;
		onSetAddingPartForRule: (ruleId: string | null) => void;
		onAddCustomSetPart: (ruleId: string, part: ProfileCatalogSearchResult) => void;
		onUpdateCustomSetPart: (ruleId: string, index: number, patch: Partial<CustomSetPart>) => void;
		onRemoveCustomSetPart: (ruleId: string, index: number) => void;
		onSetChangingSetForRule: (ruleId: string | null) => void;
		onSetRule: (ruleId: string, set: { set_num: string; name: string; year: number; num_parts: number; img_url: string | null }) => void;
		onLoadMorePreview: () => void;
	}

	let {
		rule: inputRule,
		depth,
		isPreview,
		expandedNodes,
		selectedRuleId,
		rulePreview,
		rulePreviewLoading,
		rulePreviewExpanded,
		catalogColorsLoading,
		addingPartForRule,
		changingSetForRule,
		importingCsvForRule,
		customSetImportStatus,
		fieldOptions,
		opOptionsByField,
		opLabels,
		liveRuleForRender,
		isCustomSetRule,
		conditionSummary,
		customSetPartsLabel,
		normalizeCustomColorId,
		colorLabel,
		customPartColorLabel,
		customPartColorOptions,
		formatConditionValue,
		parseConditionValue,
		onToggleNode,
		onSelectRule,
		onMoveRule,
		onDeleteRule,
		onUpdateRule,
		onAddRule,
		onAddCondition,
		onUpdateCondition,
		onDeleteCondition,
		onUpdateCustomSetName,
		onOpenBrickLinkCsvImport,
		onEnsureCatalogColorsLoaded,
		onSetAddingPartForRule,
		onAddCustomSetPart,
		onUpdateCustomSetPart,
		onRemoveCustomSetPart,
		onSetChangingSetForRule,
		onSetRule,
		onLoadMorePreview
	}: Props = $props();

	const rule = $derived(liveRuleForRender(inputRule));
	const isOpen = $derived(expandedNodes.has(rule.id));
	const hasChildren = $derived(rule.children.length > 0);
</script>

<!-- Nesting indent is halved on phones: at 16px per level a depth-4 rule would
     eat a quarter of the screen before its controls start. -->
<div class="min-w-0 {depth > 0 ? 'ml-2 border-l border-line sm:ml-4' : ''}">
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		onclick={() => {
			onToggleNode(rule.id);
			onSelectRule(rule.id);
		}}
		onkeydown={(e) => {
			if (e.target !== e.currentTarget) return;
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				onToggleNode(rule.id);
				onSelectRule(rule.id);
			}
		}}
		role="button"
		tabindex="0"
		aria-expanded={isOpen}
		class="group flex w-full cursor-pointer items-center gap-2 border-b border-line px-3 py-2 text-left transition-colors
			{isOpen ? 'bg-primary-soft' : 'hover:bg-hover'}"
	>
		{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
			<img src={rule.set_meta.img_url} alt={rule.name} class="size-16 shrink-0 object-contain" />
		{:else}
			<ChevronRight size={16} class="shrink-0 text-ink-muted transition-transform {isOpen ? 'rotate-90' : ''}" />
		{/if}
		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-2">
				<span class="truncate text-sm font-medium {rule.disabled ? 'text-ink-muted line-through' : 'text-ink'}"
					>{rule.name}</span
				>
				{#if rule.disabled}<Badge>Off</Badge>{/if}
			</div>
			{#if !isOpen}
				<div class="mt-0.5 truncate text-sm text-ink-muted">{conditionSummary(rule)}</div>
			{/if}
		</div>
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
		<div class="flex shrink-0 items-center gap-1" onclick={(e) => e.stopPropagation()}>
			{#if !isPreview}
				<span class="flex opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
					<Button variant="ghost" size="sm" icon={ChevronUp} label="Move up" onclick={() => onMoveRule(rule.id, -1)} />
					<Button variant="ghost" size="sm" icon={ChevronDown} label="Move down" onclick={() => onMoveRule(rule.id, 1)} />
					<Button variant="ghost" size="sm" icon={Trash2} label="Delete rule" onclick={() => onDeleteRule(rule.id)} />
				</span>
			{/if}
			{#if hasChildren}
				<span class="num px-1 text-sm text-ink-muted">{rule.children.length} nested</span>
			{/if}
			{#if !isPreview}
				<Switch
					checked={!rule.disabled}
					label={rule.disabled ? 'Turn the rule on' : 'Turn the rule off'}
					onchange={(on) => onUpdateRule(rule.id, { disabled: !on })}
				/>
			{/if}
		</div>
	</div>

	{#if isOpen}
		{#if rule.rule_type === 'set'}
			<div class="flex flex-col gap-3 border-b border-line px-3 py-3">
				{#if isCustomSetRule(rule)}
					<div>
						<Input
							size="sm"
							value={rule.name}
							oninput={(e) => onUpdateCustomSetName(rule.id, (e.currentTarget as HTMLInputElement).value)}
						/>
						<p class="mt-1 text-sm text-ink-muted">Custom set, {customSetPartsLabel(rule)}</p>
					</div>
					{#if catalogColorsLoading}
						<p class="flex items-center gap-2 text-sm text-ink-muted"><Spinner size={14} />Loading colors</p>
					{/if}
					<div class="flex flex-wrap items-center gap-2">
						<Button
							size="sm"
							icon={Upload}
							loading={importingCsvForRule === rule.id}
							onclick={() => onOpenBrickLinkCsvImport(rule.id)}>Import CSV</Button
						>
						<Button
							size="sm"
							icon={Plus}
							onclick={() => {
								onEnsureCatalogColorsLoaded();
								onSetAddingPartForRule(addingPartForRule === rule.id ? null : rule.id);
							}}>Add part</Button
						>
					</div>
					{#if customSetImportStatus[rule.id]}
						<Alert tone={customSetImportStatus[rule.id].tone === 'error' ? 'danger' : 'success'}>
							{customSetImportStatus[rule.id].text}
						</Alert>
					{/if}
					{#if (rule.custom_parts?.length ?? 0) === 0}
						<EmptyState title="No parts yet">Add the parts you want this custom set to collect.</EmptyState>
					{:else}
						<ul class="divide-y divide-line">
							{#each rule.custom_parts ?? [] as part, index (`${part.part_num}-${index}`)}
								{@const normalizedPartColorId = normalizeCustomColorId(part.color_id)}
								{@const partColorLabelText = part.color_name ?? colorLabel(normalizedPartColorId)}
								{@const availableColorOptions = customPartColorOptions(part)}
								<li class="flex items-start gap-3 py-2">
									{#if part.img_url}
										<img
											src={part.img_url}
											alt={part.part_name ?? part.part_num}
											class="size-14 shrink-0 object-contain"
										/>
									{:else}
										<div
											class="flex size-14 shrink-0 items-center justify-center rounded-control bg-well text-xs text-ink-muted"
										>
											Part
										</div>
									{/if}
									<div class="min-w-0 flex-1">
										<div class="truncate text-sm font-medium text-ink">{part.part_name ?? part.part_num}</div>
										<div class="truncate text-sm text-ink-muted">
											<span class="font-mono">{part.part_num}</span>{#if partColorLabelText}, {partColorLabelText}{/if}{#if part.part_source === 'bricklink'}, from a BrickLink import{/if}
										</div>
										<div class="mt-2 grid items-center gap-2 md:grid-cols-[minmax(0,1fr)_6rem_auto_auto]">
											<Select
												size="sm"
												label="Color"
												value={String(normalizedPartColorId)}
												options={availableColorOptions.map((o) => ({ value: String(o.value), label: o.label }))}
												onchange={(v: string) => {
													const nextColorId = Number(v);
													onUpdateCustomSetPart(rule.id, index, {
														color_id: nextColorId,
														color_name: customPartColorLabel(part, nextColorId)
													});
												}}
											/>
											<Input
												size="sm"
												type="number"
												min={1}
												value={part.quantity}
												oninput={(e) =>
													onUpdateCustomSetPart(rule.id, index, {
														quantity: Math.max(1, Number((e.currentTarget as HTMLInputElement).value) || 1)
													})}
											/>
											<span class="text-sm text-ink-muted">{part.quantity === 1 ? '1 part' : `${part.quantity} parts`}</span>
											<Button variant="ghost" size="sm" onclick={() => onRemoveCustomSetPart(rule.id, index)}
												>Remove</Button
											>
										</div>
									</div>
								</li>
							{/each}
						</ul>
					{/if}
					{#if addingPartForRule === rule.id}
						<PartSearch
							onSelect={(part) => onAddCustomSetPart(rule.id, part)}
							onCancel={() => onSetAddingPartForRule(null)}
						/>
					{/if}
				{:else}
					<div class="flex gap-4">
						{#if rule.set_meta?.img_url}
							<img src={rule.set_meta.img_url} alt={rule.name} class="size-32 shrink-0 object-contain" />
						{/if}
						<div class="flex min-w-0 flex-1 flex-col gap-2">
							<Input
								size="sm"
								value={rule.name}
								oninput={(e) => onUpdateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
							/>
							<p class="text-sm text-ink-muted">
								<span class="font-mono">{rule.set_num}</span>, {rule.set_meta?.year ?? '?'}, <span class="num"
									>{rule.set_meta?.num_parts ?? '?'}</span
								> parts
							</p>
							<div class="flex items-center gap-2 text-sm text-ink">
								<Switch
									checked={rule.include_spares ?? false}
									labelledby={`spares-${rule.id}`}
									onchange={(on) => onUpdateRule(rule.id, { include_spares: on } as Partial<SortingProfileRule>)}
								/>
								<span id={`spares-${rule.id}`}>Include spare parts</span>
							</div>
							<div class="flex flex-wrap items-center gap-2">
								{#if rule.set_num}
									<Button
										href={`https://rebrickable.com/sets/${rule.set_num}/`}
										target="_blank"
										rel="noopener noreferrer"
										size="sm"
										variant="ghost"
										icon={ExternalLink}>Rebrickable</Button
									>
								{/if}
								<Button
									size="sm"
									variant="ghost"
									icon={Replace}
									onclick={() => onSetChangingSetForRule(changingSetForRule === rule.id ? null : rule.id)}
									>Change set</Button
								>
							</div>
						</div>
					</div>
					{#if changingSetForRule === rule.id}
						<SetSearch onSelect={(set) => onSetRule(rule.id, set)} onCancel={() => onSetChangingSetForRule(null)} />
					{/if}
				{/if}
			</div>
		{:else}
			<div class="flex flex-col gap-3 border-b border-line px-3 py-3">
				<div class="flex items-center gap-2">
					<Input
						size="sm"
						class="min-w-0 flex-1"
						value={rule.name}
						oninput={(e) => onUpdateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
					/>
					<Select
						class="w-36 shrink-0"
						size="sm"
						label="How the conditions combine"
						value={rule.match_mode}
						options={[
							{ value: 'all', label: 'Match all' },
							{ value: 'any', label: 'Match any' }
						]}
						onchange={(v) => onUpdateRule(rule.id, { match_mode: v as SortingProfileRule['match_mode'] })}
					/>
				</div>

				{#if rule.conditions.length > 0}
					<ul class="flex flex-col gap-2">
						{#each rule.conditions as cond (cond.id)}
							<li class="flex flex-wrap items-center gap-2">
								<Select
									class="w-40 shrink-0"
									size="sm"
									label="Field"
									value={cond.field}
									options={fieldOptions.map((f) => ({ value: f, label: f }))}
									onchange={(field: string) => {
										const ops = opOptionsByField[field] ?? ['eq'];
										onUpdateCondition(rule.id, cond.id, { field, op: ops[0] });
									}}
								/>
								<Select
									class="w-28 shrink-0"
									size="sm"
									label="Comparison"
									value={cond.op}
									options={(opOptionsByField[cond.field] ?? ['eq']).map((op) => ({
										value: op,
										label: opLabels[op] ?? op
									}))}
									onchange={(op: string) => onUpdateCondition(rule.id, cond.id, { op })}
								/>
								<Input
									size="sm"
									class="min-w-0 flex-1"
									placeholder="Value"
									value={formatConditionValue(cond.value)}
									oninput={(e) =>
										onUpdateCondition(rule.id, cond.id, {
											value: parseConditionValue((e.currentTarget as HTMLInputElement).value)
										})}
								/>
								<Button
									variant="ghost"
									size="sm"
									icon={X}
									label="Remove the condition"
									onclick={() => onDeleteCondition(rule.id, cond.id)}
								/>
							</li>
						{/each}
					</ul>
				{/if}
				<div class="flex flex-wrap items-center gap-2">
					<Button variant="ghost" size="sm" icon={Plus} onclick={() => onAddCondition(rule.id)}>Condition</Button>
					<Button variant="ghost" size="sm" icon={Plus} onclick={() => onAddRule(rule.id)}>Nested rule</Button>
				</div>

				{#if hasChildren}
					<div>
						{#each rule.children as child (child.id)}
							<Self
								rule={child}
								depth={depth + 1}
								{isPreview}
								{expandedNodes}
								{selectedRuleId}
								{rulePreview}
								{rulePreviewLoading}
								{rulePreviewExpanded}
								{catalogColorsLoading}
								{addingPartForRule}
								{changingSetForRule}
								{importingCsvForRule}
								{customSetImportStatus}
								{fieldOptions}
								{opOptionsByField}
								{opLabels}
								{liveRuleForRender}
								{isCustomSetRule}
								{conditionSummary}
								{customSetPartsLabel}
								{normalizeCustomColorId}
								{colorLabel}
								{customPartColorLabel}
								{customPartColorOptions}
								{formatConditionValue}
								{parseConditionValue}
								{onToggleNode}
								{onSelectRule}
								{onMoveRule}
								{onDeleteRule}
								{onUpdateRule}
								{onAddRule}
								{onAddCondition}
								{onUpdateCondition}
								{onDeleteCondition}
								{onUpdateCustomSetName}
								{onOpenBrickLinkCsvImport}
								{onEnsureCatalogColorsLoaded}
								{onSetAddingPartForRule}
								{onAddCustomSetPart}
								{onUpdateCustomSetPart}
								{onRemoveCustomSetPart}
								{onSetChangingSetForRule}
								{onSetRule}
								{onLoadMorePreview}
							/>
						{/each}
					</div>
				{/if}

				{#if selectedRuleId === rule.id && rulePreview}
					<div class="rounded-control bg-well px-3 py-2">
						<div class="mb-1 flex items-center justify-between text-sm text-ink-muted">
							<span class="num">{rulePreview.total} matching parts</span>
							{#if rulePreviewLoading}<Spinner size={14} />{/if}
						</div>
						{#if rulePreview.sample.length > 0}
							<ul class="flex flex-col gap-0.5">
								{#each rulePreview.sample as part, i (i)}
									<li class="truncate text-sm text-ink-muted">
										<span class="font-mono">{part.part_num}</span>
										{part.name}
									</li>
								{/each}
							</ul>
							{#if !rulePreviewExpanded && rulePreview.total > 5}
								<Button variant="ghost" size="sm" onclick={onLoadMorePreview}
									>Show more of the {rulePreview.total}</Button
								>
							{/if}
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	{/if}
</div>
