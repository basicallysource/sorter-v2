<script lang="ts">
	import type { CustomSetPart, ProfileCatalogSearchResult, SortingProfileRule } from '$lib/api';
	import PartSearch from '$lib/components/profile/PartSearch.svelte';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import Self from './RuleAccordionNode.svelte';

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

<div class="{depth > 0 ? 'ml-4 border-l border-border' : ''}">
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div onclick={() => { onToggleNode(rule.id); onSelectRule(rule.id); }}
		onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { onToggleNode(rule.id); onSelectRule(rule.id); } }}
		role="button" tabindex="0"
		class="group flex w-full cursor-pointer items-center gap-2 border-b border-border px-3 py-2 text-left transition-colors hover:bg-bg
			{isOpen ? 'bg-primary/8' : ''}">
		{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
			<img src={rule.set_meta.img_url} alt={rule.name} class="h-16 w-16 shrink-0 object-contain" />
		{:else}
			<svg class="h-3.5 w-3.5 shrink-0 text-text-muted transition-transform {isOpen ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
			</svg>
		{/if}
		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-2">
				<span class="truncate text-sm font-medium {rule.disabled ? 'text-text-muted line-through' : 'text-text'}">{rule.name}</span>
				{#if rule.disabled}
					<span class="shrink-0 text-[10px] uppercase tracking-wide text-text-muted">off</span>
				{/if}
			</div>
			{#if !isOpen}
				<div class="mt-0.5 truncate text-xs text-text-muted">
					{conditionSummary(rule)}
				</div>
			{/if}
		</div>
		<div class="flex shrink-0 items-center gap-2">
			{#if !isPreview}
				<button onclick={(e) => { e.stopPropagation(); onMoveRule(rule.id, -1); }}
					class="p-1 text-text-muted hover:text-text opacity-0 group-hover:opacity-100 transition-opacity" aria-label="Move up" title="Move up">
					<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
					</svg>
				</button>
				<button onclick={(e) => { e.stopPropagation(); onMoveRule(rule.id, 1); }}
					class="p-1 text-text-muted hover:text-text opacity-0 group-hover:opacity-100 transition-opacity" aria-label="Move down" title="Move down">
					<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
					</svg>
				</button>
				<button onclick={(e) => { e.stopPropagation(); onDeleteRule(rule.id); }}
					class="p-1 text-primary opacity-0 group-hover:opacity-100 transition-opacity hover:text-primary-hover" aria-label="Delete rule" title="Delete">
					<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
					</svg>
				</button>
			{/if}
			{#if hasChildren}
				<span class="text-xs text-text-muted">{rule.children.length} sub</span>
			{/if}
			{#if !isPreview}
				<button onclick={(e) => { e.stopPropagation(); onUpdateRule(rule.id, { disabled: !rule.disabled }); }}
					class="relative inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full transition-colors {rule.disabled ? 'bg-gray-300' : 'bg-success'}"
					title={rule.disabled ? 'Enable rule' : 'Disable rule'}
					role="switch"
					aria-checked={!rule.disabled}>
					<span class="inline-block h-3 w-3 rounded-full bg-white shadow transition-transform {rule.disabled ? 'translate-x-0.5' : 'translate-x-3.5'}"></span>
				</button>
			{/if}
		</div>
	</div>

	{#if isOpen}
		{#if rule.rule_type === 'set'}
			<div class="border-b border-border bg-white px-3 py-3">
				{#if isCustomSetRule(rule)}
					<div class="mb-3">
						<input
							type="text"
							value={rule.name}
							oninput={(e) => onUpdateCustomSetName(rule.id, (e.currentTarget as HTMLInputElement).value)}
							class="mb-1 w-full border border-border px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						/>
						<div class="text-xs text-text-muted">
							Custom set · {customSetPartsLabel(rule)}
						</div>
					</div>
					{#if catalogColorsLoading}
						<div class="mb-3 text-xs text-text-muted">Loading colors...</div>
					{/if}
					<div class="mb-3 flex items-center gap-2">
						<button onclick={() => onOpenBrickLinkCsvImport(rule.id)}
							disabled={importingCsvForRule === rule.id}
							class="border border-border bg-white px-3 py-1.5 text-xs font-medium text-text-muted hover:bg-bg hover:text-text disabled:opacity-50">
							{importingCsvForRule === rule.id ? 'Importing...' : 'Import CSV'}
						</button>
						<button onclick={() => {
							onEnsureCatalogColorsLoaded();
							onSetAddingPartForRule(addingPartForRule === rule.id ? null : rule.id);
						}}
							class="border border-border bg-white px-3 py-1.5 text-xs font-medium text-text-muted hover:bg-bg hover:text-text">
							Add Part
						</button>
					</div>
					{#if customSetImportStatus[rule.id]}
						<div class="mb-3 border px-3 py-2 text-xs {customSetImportStatus[rule.id].tone === 'error'
							? 'border-[#F4C7C7] bg-primary/8 text-danger'
							: 'border-[#CDE5D5] bg-[#F2FAF5] text-[#2F6B42]'}">
							{customSetImportStatus[rule.id].text}
						</div>
					{/if}
					<div class="space-y-2">
						{#if (rule.custom_parts?.length ?? 0) === 0}
							<div class="border border-dashed border-border px-3 py-4 text-center text-xs text-text-muted">
								No parts yet. Add the items you want this custom set to collect.
							</div>
						{:else}
							{#each rule.custom_parts ?? [] as part, index (`${part.part_num}-${index}`)}
								{@const normalizedPartColorId = normalizeCustomColorId(part.color_id)}
								{@const partColorLabelText = part.color_name ?? colorLabel(normalizedPartColorId)}
								{@const availableColorOptions = customPartColorOptions(part)}
								<div class="flex items-start gap-3 border border-border p-2">
									{#if part.img_url}
										<img src={part.img_url} alt={part.part_name ?? part.part_num} class="h-14 w-14 shrink-0 object-contain" />
									{:else}
										<div class="flex h-14 w-14 shrink-0 items-center justify-center bg-bg text-[10px] uppercase tracking-wide text-text-muted">Part</div>
									{/if}
									<div class="min-w-0 flex-1">
										<div class="truncate text-sm font-medium text-text">
											{part.part_name ?? part.part_num}
										</div>
										<div class="truncate text-xs text-text-muted">
											{part.part_num}
											{#if partColorLabelText}
												· {partColorLabelText}
											{/if}
											{#if part.part_source === 'bricklink'}
												· BrickLink import
											{/if}
										</div>
										<div class="mt-2 grid gap-2 md:grid-cols-[minmax(0,1fr)_96px_80px_auto]">
											<select
												onchange={(e) => {
													const nextColorId = Number((e.currentTarget as HTMLSelectElement).value);
													onUpdateCustomSetPart(rule.id, index, {
														color_id: nextColorId,
														color_name: customPartColorLabel(part, nextColorId)
													});
												}}
												class="min-w-0 border border-border px-2 py-1 text-xs focus:border-primary focus:outline-none"
											>
												{#each availableColorOptions as option (`${part.part_num}-${option.value}`)}
													<option value={option.value} selected={option.value === normalizedPartColorId}>{option.label}</option>
												{/each}
											</select>
											<input
												type="number"
												min="1"
												value={String(part.quantity)}
												oninput={(e) => onUpdateCustomSetPart(rule.id, index, {
													quantity: Math.max(1, Number((e.currentTarget as HTMLInputElement).value) || 1)
												})}
												class="border border-border px-2 py-1 text-xs focus:border-primary focus:outline-none"
											/>
											<div class="flex items-center text-xs text-text-muted">
												{part.quantity === 1 ? '1 part' : `${part.quantity} parts`}
											</div>
											<button
												onclick={() => onRemoveCustomSetPart(rule.id, index)}
												class="px-2 py-1 text-xs text-primary hover:text-primary-hover"
											>
												Remove
											</button>
										</div>
									</div>
								</div>
							{/each}
						{/if}
					</div>
					{#if addingPartForRule === rule.id}
						<div class="mt-3">
							<PartSearch
								onSelect={(part) => onAddCustomSetPart(rule.id, part)}
								onCancel={() => onSetAddingPartForRule(null)}
							/>
						</div>
					{/if}
				{:else}
					<div class="mb-3 flex gap-4">
						{#if rule.set_meta?.img_url}
							<img src={rule.set_meta.img_url} alt={rule.name} class="h-32 w-32 shrink-0 object-contain" />
						{/if}
						<div class="min-w-0 flex-1">
							<input type="text" value={rule.name}
								oninput={(e) => onUpdateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
								class="mb-1 w-full border border-border px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
							<div class="mb-2 text-xs text-text-muted">
								{rule.set_num} · {rule.set_meta?.year ?? '?'} · {rule.set_meta?.num_parts ?? '?'} parts
							</div>
							{#if rule.set_num}
								<a href={`https://rebrickable.com/sets/${rule.set_num}/`}
									target="_blank" rel="noopener noreferrer"
									class="inline-flex items-center gap-1 text-xs text-primary hover:underline">
									View on Rebrickable
									<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
										<path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.25-.75a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V6.31l-5.97 5.97a.75.75 0 01-1.06-1.06l5.97-5.97H12.25a.75.75 0 01-.75-.75z" clip-rule="evenodd" />
									</svg>
								</a>
							{/if}
						</div>
					</div>
					<div class="mb-3 flex items-center gap-4">
						<label class="flex items-center gap-2 text-xs text-text-muted">
							<button onclick={() => onUpdateRule(rule.id, { include_spares: !(rule.include_spares ?? false) } as Partial<SortingProfileRule>)}
								class="relative inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full transition-colors {rule.include_spares ? 'bg-success' : 'bg-gray-300'}"
								role="switch"
								aria-checked={rule.include_spares ?? false}
								type="button">
								<span class="inline-block h-3 w-3 rounded-full bg-white shadow transition-transform {rule.include_spares ? 'translate-x-3.5' : 'translate-x-0.5'}"></span>
							</button>
							Include spare parts
						</label>
					</div>
					{#if changingSetForRule === rule.id}
						<div class="mb-3">
							<SetSearch onSelect={(set) => onSetRule(rule.id, set)}
								onCancel={() => onSetChangingSetForRule(null)} />
						</div>
					{/if}
				{/if}
				{#if !isCustomSetRule(rule)}
					<div class="flex items-center gap-2 border-t border-border pt-2">
						<button onclick={() => onSetChangingSetForRule(changingSetForRule === rule.id ? null : rule.id)}
							class="text-xs text-primary hover:text-primary-hover">
							Change Set
						</button>
					</div>
				{/if}
			</div>
		{:else}
			<div class="border-b border-border bg-white px-3 py-3">
				<div class="mb-3 flex items-center gap-2">
					<input type="text" value={rule.name}
						oninput={(e) => onUpdateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
						class="min-w-0 flex-1 border border-border px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
					<select value={rule.match_mode}
						onchange={(e) => onUpdateRule(rule.id, { match_mode: (e.currentTarget as HTMLSelectElement).value as SortingProfileRule['match_mode'] })}
						class="border border-border px-2 py-1 text-xs text-text-muted focus:border-primary focus:outline-none">
						<option value="all">Match ALL</option>
						<option value="any">Match ANY</option>
					</select>
				</div>

				{#if rule.conditions.length > 0}
					<div class="mb-2 space-y-1.5">
						{#each rule.conditions as cond (cond.id)}
							<div class="flex items-center gap-1.5">
								<select value={cond.field}
									onchange={(e) => {
										const field = (e.currentTarget as HTMLSelectElement).value;
										const ops = opOptionsByField[field] ?? ['eq'];
										onUpdateCondition(rule.id, cond.id, { field, op: ops[0] });
									}}
									class="w-36 border border-border px-1.5 py-1 text-xs focus:border-primary focus:outline-none">
									{#each fieldOptions as f}
										<option value={f}>{f}</option>
									{/each}
								</select>
								<select value={cond.op}
									onchange={(e) => onUpdateCondition(rule.id, cond.id, { op: (e.currentTarget as HTMLSelectElement).value })}
									class="w-20 border border-border px-1.5 py-1 text-xs focus:border-primary focus:outline-none">
									{#each opOptionsByField[cond.field] ?? ['eq'] as op}
										<option value={op}>{opLabels[op] ?? op}</option>
									{/each}
								</select>
								<input type="text" value={formatConditionValue(cond.value)}
									oninput={(e) => onUpdateCondition(rule.id, cond.id, { value: parseConditionValue((e.currentTarget as HTMLInputElement).value) })}
									class="min-w-0 flex-1 border border-border px-1.5 py-1 text-xs focus:border-primary focus:outline-none"
									placeholder="value" />
								<button onclick={() => onDeleteCondition(rule.id, cond.id)}
									class="shrink-0 p-1 text-text-muted hover:text-primary" aria-label="Remove condition">
									<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
										<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
									</svg>
								</button>
							</div>
						{/each}
					</div>
				{/if}
				<button onclick={() => onAddCondition(rule.id)}
					class="mb-3 text-xs font-medium text-primary hover:text-primary-hover">+ Add condition</button>

				{#if hasChildren}
					<div class="mb-2">
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

				<div class="flex items-center gap-2 border-t border-border pt-2">
					<button onclick={() => onAddRule(rule.id)}
						class="text-xs font-medium text-primary hover:text-primary-hover">+ Add child</button>
				</div>

				{#if selectedRuleId === rule.id && rulePreview}
					<div class="mt-2 border-t border-border pt-2">
						<div class="mb-1 flex items-center justify-between text-xs text-text-muted">
							<span>{rulePreview.total} matching parts</span>
							{#if rulePreviewLoading}
								<span class="text-text-muted">Loading...</span>
							{/if}
						</div>
						{#if rulePreview.sample.length > 0}
							<div class="space-y-0.5">
								{#each rulePreview.sample as part}
									<div class="truncate text-xs text-text-muted">{part.part_num} — {part.name}</div>
								{/each}
							</div>
							{#if !rulePreviewExpanded && rulePreview.total > 5}
								<button onclick={onLoadMorePreview} class="mt-1 text-xs text-primary hover:text-primary-hover">
									Show more ({rulePreview.total} total)
								</button>
							{/if}
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	{/if}
</div>
