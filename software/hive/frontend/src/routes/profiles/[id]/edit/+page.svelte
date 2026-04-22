<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { tick } from 'svelte';
	import {
		api,
		type AiToolTraceItem,
		type BrickLinkCsvImportResult,
		type CustomSetPart,
		type ProfileCatalogColor,
		type ProfileCatalogSearchResult,
		type SortingProfileAiMessage,
		type SortingProfileDetail,
		type SortingProfileFallbackMode,
		type SortingProfileRule
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import PartSearch from '$lib/components/profile/PartSearch.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import ProfileChatPanel from '$lib/components/profile/edit/ProfileChatPanel.svelte';
	import RuleAccordionNode from '$lib/components/profile/edit/RuleAccordionNode.svelte';
	import { Alert, Button } from '$lib/components/primitives';
	import {
		aiMessagePerformanceLabel,
		buildAiProgressCards,
		displayAiMessageContent,
		formatDuration,
		getExpandableToolResult,
		getToolResultSummaryLine,
		proposalActionSummaries,
		toolTraceTitle,
		TOOL_RESULT_COLLAPSED_COUNT,
		type AiProgressEvent,
		type AiProgressCard,
		type ExpandableToolResult,
		type ToolResultListItem
	} from '$lib/components/profile/edit/chat-helpers';
	import { renderMarkdown } from '$lib/markdown';

	const ANY_COLOR_ID = -1;

	type RulePreviewResult = {
		total: number;
		sample: Array<Record<string, unknown>>;
		offset: number;
		limit: number;
	};


	// --- State ---
	let loading = $state(true);
	let profile = $state<SortingProfileDetail | null>(null);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);

	let workingRules = $state<SortingProfileRule[]>([]);
	let workingFallbackMode = $state<SortingProfileFallbackMode>({
		rebrickable_categories: false,
		bricklink_categories: false,
		by_color: false
	});
	let workingDefaultCategoryId = $state('');

	let originalRulesJson = $state('');
	let originalFallbackJson = $state('');
	let originalDefaultCategoryId = $state('');

	let selectedRuleId = $state<string | null>(null);
	let expandedNodes = $state<Set<string>>(new Set());

	let showSetSearch = $state(false);
	let changingSetForRule = $state<string | null>(null);
	let addingPartForRule = $state<string | null>(null);
	let pendingCsvImportRule = $state<string | null>(null);
	let importingCsvForRule = $state<string | null>(null);
	let savingVersion = $state(false);
	let showSavePopover = $state(false);
	let changeNote = $state('');
	let catalogColors = $state<ProfileCatalogColor[]>([]);
	let catalogColorsLoading = $state(false);
	let csvImportFileInput: HTMLInputElement | undefined = $state(undefined);
	let customSetImportStatus = $state<Record<string, { tone: 'success' | 'error'; text: string }>>({});

	let rulePreview = $state<RulePreviewResult | null>(null);
	let rulePreviewLoading = $state(false);
	let rulePreviewExpanded = $state(false);
	let previewDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	// Right panel tab
	let rightTab = $state<'chat' | 'versions'>('chat');
	let restoringVersionId = $state<string | null>(null);

	// Version preview
	let previewVersion = $state<import('$lib/api').SortingProfileVersion | null>(null);
	let previewLoading = $state(false);

	// AI state
	let aiMessages = $state<SortingProfileAiMessage[]>([]);
	let aiMessage = $state('');
	let aiBusy = $state(false);
	let aiProgress = $state<AiProgressEvent[]>([]);
	let expandedToolResults = $state<Set<string>>(new Set());

	const profileId = $derived(page.params.id ?? '');
	const isNewProfile = $derived(page.url.searchParams.get('new') === '1');

	const hasOpenRouter = $derived(Boolean(auth.user?.openrouter_configured));

	const hasUnsavedChanges = $derived.by(() => {
		if (!profile) return false;
		return (
			JSON.stringify(workingRules) !== originalRulesJson ||
			JSON.stringify(workingFallbackMode) !== originalFallbackJson ||
			workingDefaultCategoryId !== originalDefaultCategoryId
		);
	});

	const selectedRule = $derived.by(() => {
		if (!selectedRuleId) return null;
		return findRule(workingRules, selectedRuleId);
	});

	const compiledStats = $derived.by(() => {
		const cv = profile?.current_version;
		if (!cv?.compiled_stats) return null;
		return cv.compiled_stats;
	});

	const perCategoryStats = $derived.by(() => {
		const stats = compiledStats;
		if (!stats || typeof stats.per_category !== 'object' || stats.per_category === null) return {};
		return stats.per_category as Record<string, { parts?: number; colors?: number }>;
	});

	const aiProgressCards = $derived.by(() => buildAiProgressCards(aiProgress));
	const visibleAiProgressCards = $derived.by(() => {
		const completedTools = aiProgressCards.filter(
			(card) => card.kind === 'tool' && card.status === 'complete'
		);
		const activeCard = [...aiProgressCards].reverse().find((card) => card.status === 'active');
		const stableCompletedTools =
			completedTools.length <= 5
				? completedTools
				: [
					...completedTools.slice(0, 2),
					...completedTools.slice(-3)
				].filter((card, index, all) => all.findIndex((entry) => entry.id === card.id) === index);
		return activeCard ? [...stableCompletedTools, activeCard] : stableCompletedTools;
	});

	// --- Field / Op config ---
	const fieldOptions: string[] = [
		'name', 'part_num', 'category_id', 'category_name', 'color_id',
		'year_from', 'year_to', 'bricklink_id', 'bricklink_item_count',
		'bricklink_primary_item_no', 'bl_price_min', 'bl_price_max',
		'bl_price_avg', 'bl_price_qty_avg', 'bl_price_lots', 'bl_price_qty',
		'bl_catalog_name', 'bl_catalog_category_id', 'bl_category_id',
		'bl_category_name', 'bl_catalog_year_released', 'bl_catalog_weight',
		'bl_catalog_dim_x', 'bl_catalog_dim_y', 'bl_catalog_dim_z',
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

	const opLabels: Record<string, string> = {
		eq: '=', neq: '!=', in: 'in', contains: 'contains',
		regex: 'regex', gte: '>=', lte: '<='
	};

	// --- Navigation guard ---
	beforeNavigate(({ cancel }) => {
		if (hasUnsavedChanges && !confirm('You have unsaved changes. Leave anyway?')) {
			cancel();
		}
	});

	// --- Load profile ---
	let lastLoadedProfileId = '';

	$effect(() => {
		const nextProfileId = profileId;
		if (!nextProfileId) return;
		if (nextProfileId === lastLoadedProfileId) return;
		lastLoadedProfileId = nextProfileId;
		void loadProfile();
	});

	// --- Debounced rule preview ---
	$effect(() => {
		const ruleId = selectedRuleId;
		if (!ruleId) {
			rulePreview = null;
			return;
		}
		if (selectedRule?.rule_type === 'set') {
			if (previewDebounceTimer) clearTimeout(previewDebounceTimer);
			rulePreview = null;
			rulePreviewLoading = false;
			return;
		}
		rulePreviewExpanded = false;
		if (previewDebounceTimer) clearTimeout(previewDebounceTimer);
		previewDebounceTimer = setTimeout(() => {
			void loadRulePreview(ruleId);
		}, 500);
	});

	// --- Auto-scroll AI chat ---
	let chatContainer: HTMLDivElement | undefined = $state(undefined);

	$effect(() => {
		// Track message count, busy state, and progress updates for auto-scroll
		void aiMessages.length;
		void aiBusy;
		void aiProgress.length;
		if (chatContainer) {
			requestAnimationFrame(() => {
				chatContainer?.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
			});
		}
	});

	async function loadProfile() {
		if (!profileId) return;
		loading = true;
		error = null;
		try {
			const detail = await api.getSortingProfile(profileId);
			profile = detail;
			hydrateWorkingState(detail);
			void ensureCatalogColorsLoaded();
			if (detail.is_owner) {
				aiMessages = await api.getSortingProfileAiMessages(profileId);
			}
		} catch (e: any) {
			error = e.error || 'Failed to load profile';
		} finally {
			loading = false;
		}
	}

	function hydrateWorkingState(detail: SortingProfileDetail) {
		const cv = detail.current_version;
		if (!cv) return;
		const normalizedRules = normalizeRuleTree(structuredClone(cv.rules));
		workingRules = normalizedRules;
		workingFallbackMode = structuredClone(cv.fallback_mode);
		workingDefaultCategoryId = cv.default_category_id ?? '';
		originalRulesJson = JSON.stringify(normalizedRules);
		originalFallbackJson = JSON.stringify(cv.fallback_mode);
		originalDefaultCategoryId = cv.default_category_id ?? '';
		selectedRuleId = normalizedRules[0]?.id ?? null;
		expandedNodes = new Set();
	}

	async function ensureCatalogColorsLoaded() {
		if (catalogColorsLoading || catalogColors.length > 0) return;
		catalogColorsLoading = true;
		try {
			const res = await api.getProfileCatalogColors();
			catalogColors = res.results;
		} catch {
			catalogColors = [];
		} finally {
			catalogColorsLoading = false;
		}
	}

	// --- Rule tree helpers ---
	function findRule(rules: SortingProfileRule[], ruleId: string): SortingProfileRule | null {
		for (const rule of rules) {
			if (rule.id === ruleId) return rule;
			const found = findRule(rule.children, ruleId);
			if (found) return found;
		}
		return null;
	}

	function normalizeRuleTree(rules: SortingProfileRule[]): SortingProfileRule[] {
		return rules.map((rule) => {
			const setSource =
				rule.rule_type === 'set'
					? (rule.set_source ?? (rule.custom_parts?.length ? 'custom' : 'rebrickable'))
					: undefined;
			const normalized: SortingProfileRule = {
				...rule,
				rule_type: rule.rule_type ?? 'filter',
				children: normalizeRuleTree(rule.children ?? [])
			};
			if (normalized.rule_type === 'set') {
				normalized.set_source = setSource;
				normalized.custom_parts = (normalized.custom_parts ?? []).map((part) => ({
					...part,
					color_id: normalizeCustomColorId(part.color_id)
				}));
				if (normalized.set_source === 'custom') {
					normalized.set_meta = buildCustomSetMeta(normalized);
				}
			}
			return normalized;
		});
	}

	function isCustomSetRule(rule: SortingProfileRule): boolean {
		return rule.rule_type === 'set' && (rule.set_source === 'custom' || (rule.custom_parts?.length ?? 0) > 0);
	}

	function normalizeCustomColorId(colorId: number | string | null | undefined): number {
		if (colorId === null || colorId === undefined || colorId === '' || colorId === 'any' || colorId === 'any_color') {
			return ANY_COLOR_ID;
		}
		const numeric = Number(colorId);
		return Number.isFinite(numeric) ? numeric : ANY_COLOR_ID;
	}

	function buildCustomSetMeta(rule: SortingProfileRule): NonNullable<SortingProfileRule['set_meta']> {
		const parts = rule.custom_parts ?? [];
		const totalQuantity = parts.reduce((sum, part) => sum + Math.max(0, Number(part.quantity) || 0), 0);
		return {
			name: rule.name || 'Custom Set',
			year: null,
			num_parts: totalQuantity,
			img_url: null
		};
	}

	function syncCustomSetRule(rule: SortingProfileRule) {
		if (!isCustomSetRule(rule)) return;
		rule.set_source = 'custom';
		rule.include_spares = false;
		rule.set_num = rule.set_num || `custom:${rule.id}`;
		rule.custom_parts = (rule.custom_parts ?? []).map((part) => ({
			...part,
			color_id: normalizeCustomColorId(part.color_id)
		}));
		rule.set_meta = buildCustomSetMeta(rule);
	}

	function customSetLineCount(rule: SortingProfileRule): number {
		return rule.custom_parts?.length ?? 0;
	}

	function customSetPartsLabel(rule: SortingProfileRule): string {
		const total = buildCustomSetMeta(rule).num_parts ?? 0;
		const lineCount = customSetLineCount(rule);
		const lineLabel = lineCount === 1 ? 'line item' : 'line items';
		const partLabel = total === 1 ? 'part' : 'parts';
		return `${lineCount} ${lineLabel} · ${total} ${partLabel}`;
	}

	function colorLabel(colorId: number | string | null | undefined, fallback?: string | null): string {
		if (fallback) return fallback;
		const numeric = Number(colorId);
		if (numeric === ANY_COLOR_ID) return 'Any color';
		return catalogColors.find((color) => color.id === numeric)?.name ?? String(colorId ?? '');
	}

	function customPartColorLabel(part: CustomSetPart, colorId: number | string | null | undefined): string {
		const normalized = normalizeCustomColorId(colorId);
		if (normalized === ANY_COLOR_ID) return 'Any color';
		if ((part.part_source ?? 'rebrickable') === 'bricklink' && normalizeCustomColorId(part.color_id) === normalized) {
			return part.color_name ?? `BrickLink color ${normalized}`;
		}
		return colorLabel(normalized);
	}

	function customPartColorOptions(part: CustomSetPart): Array<{ value: number; label: string }> {
		const normalized = normalizeCustomColorId(part.color_id);
		const options =
			(part.part_source ?? 'rebrickable') === 'bricklink'
				? [
					{ value: ANY_COLOR_ID, label: 'Any color' },
					...(normalized !== ANY_COLOR_ID
						? [{
							value: normalized,
							label: part.color_name ?? `BrickLink color ${normalized}`
						}]
						: [])
				]
				: [
					{ value: ANY_COLOR_ID, label: 'Any color' },
					...catalogColors
						.filter((color) => color.id !== ANY_COLOR_ID)
						.map((color) => ({ value: color.id, label: color.name }))
				];

		// The catalog includes an "unknown" sentinel with id -1, which would duplicate
		// our explicit "Any color" option and crash the keyed <option> loop.
		const seen = new Set<number>();
		return options.filter((option) => {
			if (seen.has(option.value)) return false;
			seen.add(option.value);
			return true;
		});
	}

	function mergeCustomSetParts(existing: CustomSetPart[], imported: CustomSetPart[]): CustomSetPart[] {
		const merged = new Map<string, CustomSetPart>();
		for (const part of [...existing, ...imported]) {
			const colorId = normalizeCustomColorId(part.color_id);
			const partSource = part.part_source ?? 'rebrickable';
			const key = `${partSource}::${part.part_num}::${colorId}`;
			const current = merged.get(key);
			if (current) {
				current.quantity += Math.max(0, Number(part.quantity) || 0);
				if (!current.part_name && part.part_name) current.part_name = part.part_name;
				if (!current.color_name && part.color_name) current.color_name = part.color_name;
				if (!current.img_url && part.img_url) current.img_url = part.img_url;
				continue;
			}
			merged.set(key, {
				...part,
				part_source: partSource,
				color_id: colorId,
				color_name: part.color_name ?? colorLabel(colorId),
				quantity: Math.max(0, Number(part.quantity) || 0)
			});
		}
		return [...merged.values()].filter((part) => part.quantity > 0);
	}

	function updateRuleList(
		rules: SortingProfileRule[],
		ruleId: string,
		mutator: (rule: SortingProfileRule, siblings: SortingProfileRule[], index: number) => void
	): boolean {
		for (let index = 0; index < rules.length; index += 1) {
			const rule = rules[index];
			if (rule.id === ruleId) {
				mutator(rule, rules, index);
				return true;
			}
			if (updateRuleList(rule.children, ruleId, mutator)) return true;
		}
		return false;
	}

	function withRules(mutator: (rules: SortingProfileRule[]) => void) {
		const nextRules = structuredClone($state.snapshot(workingRules)) as SortingProfileRule[];
		mutator(nextRules);
		workingRules = normalizeRuleTree(nextRules);
	}

	function makeRule(name = 'New Category'): SortingProfileRule {
		return {
			id: crypto.randomUUID(),
			name,
			match_mode: 'all',
			conditions: [],
			children: [],
			disabled: false
		};
	}

	function makeCustomSetRule(name = 'Custom Set'): SortingProfileRule {
		const rule: SortingProfileRule = {
			id: crypto.randomUUID(),
			rule_type: 'set',
			set_source: 'custom',
			name,
			match_mode: 'all',
			conditions: [],
			children: [],
			disabled: false,
			set_num: '',
			include_spares: false,
			set_meta: {
				name,
				year: null,
				num_parts: 0,
				img_url: null
			},
			custom_parts: []
		};
		syncCustomSetRule(rule);
		return rule;
	}

	// --- Rule manipulation ---
	function addRule(parentId?: string) {
		if (parentId) {
			withRules((rules) => {
				updateRuleList(rules, parentId, (rule) => {
					const child = makeRule(`${rule.name} Child ${rule.children.length + 1}`);
					rule.children.push(child);
					expandedNodes = new Set([...expandedNodes, parentId]);
					selectedRuleId = child.id;
				});
			});
		} else {
			const newRule = makeRule(`Rule ${workingRules.length + 1}`);
			withRules((rules) => rules.push(newRule));
			selectedRuleId = newRule.id;
			expandedNodes = new Set([...expandedNodes, newRule.id]);
		}
	}

	function addSetRule(set: { set_num: string; name: string; year: number; num_parts: number; img_url: string | null }) {
		const newRule: SortingProfileRule = {
			id: crypto.randomUUID(),
			rule_type: 'set',
			set_source: 'rebrickable',
			name: set.name,
			match_mode: 'all',
			conditions: [],
			children: [],
			disabled: false,
			set_num: set.set_num,
			include_spares: false,
			custom_parts: [],
			set_meta: {
				name: set.name,
				year: set.year,
				num_parts: set.num_parts,
				img_url: set.img_url
			}
		};
		withRules((rules) => rules.push(newRule));
		selectedRuleId = newRule.id;
		showSetSearch = false;
	}

	function addCustomSetRule() {
		const newRule = makeCustomSetRule(`Custom Set ${workingRules.filter((rule) => isCustomSetRule(rule)).length + 1}`);
		withRules((rules) => rules.push(newRule));
		selectedRuleId = newRule.id;
		expandedNodes = new Set([...expandedNodes, newRule.id]);
		void ensureCatalogColorsLoaded();
	}

	function openBrickLinkCsvImport(ruleId: string) {
		pendingCsvImportRule = ruleId;
		customSetImportStatus = Object.fromEntries(
			Object.entries(customSetImportStatus).filter(([key]) => key !== ruleId)
		);
		csvImportFileInput?.click();
	}

	async function handleBrickLinkCsvSelected(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		const ruleId = pendingCsvImportRule;
		input.value = '';
		if (!file || !ruleId) {
			pendingCsvImportRule = null;
			return;
		}
		pendingCsvImportRule = null;
		importingCsvForRule = ruleId;

		try {
			const csvContent = await file.text();
			const result = await api.importProfileCatalogBricklinkCsv(csvContent, file.name);
			await applyBrickLinkCsvImport(ruleId, result);
		} catch (e: any) {
			customSetImportStatus = {
				...customSetImportStatus,
				[ruleId]: {
					tone: 'error',
					text: e?.error || 'Failed to import BrickLink CSV'
				}
			};
		} finally {
			importingCsvForRule = null;
		}
	}

	async function applyBrickLinkCsvImport(ruleId: string, result: BrickLinkCsvImportResult) {
		let importedLineItems = 0;
		let updated = false;
		withRules((rules) => {
			updated = updateRuleList(rules, ruleId, (rule) => {
				const existingParts = rule.custom_parts ?? [];
				rule.custom_parts = mergeCustomSetParts(existingParts, result.parts);
				if (
					(!rule.name || rule.name.trim() === '' || rule.name.startsWith('Custom Set')) &&
					result.suggested_name
				) {
					rule.name = result.suggested_name;
				}
				syncCustomSetRule(rule);
				importedLineItems = rule.custom_parts?.length ?? 0;
			});
		});
		if (!updated) {
			customSetImportStatus = {
				...customSetImportStatus,
				[ruleId]: {
					tone: 'error',
					text: 'Imported the CSV, but could not apply it to this custom set. Please try again.'
				}
			};
			return;
		}
		selectedRuleId = ruleId;
		expandedNodes = new Set([...expandedNodes, ruleId]);
		addingPartForRule = null;
		await tick();

		const warningText =
			result.warning_count > 0
				? ` Imported ${result.imported_rows} rows with ${result.warning_count} warnings.${result.warnings[0] ? ` First issue: ${result.warnings[0]}` : ''}`
				: '';
		customSetImportStatus = {
			...customSetImportStatus,
			[ruleId]: {
				tone: 'success',
				text: `Imported ${result.imported_unique_parts} unique parts from BrickLink CSV into ${importedLineItems} line items.${warningText}`
			}
		};
	}

	function updateCustomSetName(ruleId: string, name: string) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				rule.name = name;
				syncCustomSetRule(rule);
			});
		});
	}

	function addCustomSetPart(ruleId: string, part: ProfileCatalogSearchResult) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				const nextPart: CustomSetPart = {
					part_num: part.part_num,
					part_name: part.name,
					img_url: part.part_img_url,
					part_source: 'rebrickable',
					color_id: ANY_COLOR_ID,
					color_name: 'Any color',
					quantity: 1
				};
				rule.custom_parts = [...(rule.custom_parts ?? []), nextPart];
				syncCustomSetRule(rule);
			});
		});
		addingPartForRule = null;
	}

	function updateCustomSetPart(ruleId: string, index: number, patch: Partial<CustomSetPart>) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				const parts = [...(rule.custom_parts ?? [])];
				const current = parts[index];
				if (!current) return;
				const nextColorId =
					patch.color_id !== undefined
						? normalizeCustomColorId(patch.color_id)
						: normalizeCustomColorId(current.color_id ?? ANY_COLOR_ID);
				const nextColorName =
					patch.color_name !== undefined
						? patch.color_name
						: customPartColorLabel(current, nextColorId);
				parts[index] = {
					...current,
					...patch,
					color_id: nextColorId,
					color_name: nextColorName ?? current.color_name ?? null
				};
				rule.custom_parts = parts;
				syncCustomSetRule(rule);
			});
		});
	}

	function removeCustomSetPart(ruleId: string, index: number) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				rule.custom_parts = (rule.custom_parts ?? []).filter((_, partIndex) => partIndex !== index);
				syncCustomSetRule(rule);
			});
		});
	}

	function deleteRule(ruleId: string) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (_rule, siblings, index) => siblings.splice(index, 1));
		});
		if (selectedRuleId === ruleId) selectedRuleId = workingRules[0]?.id ?? null;
	}

	function moveRule(ruleId: string, direction: -1 | 1) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (_rule, siblings, index) => {
				const nextIndex = index + direction;
				if (nextIndex < 0 || nextIndex >= siblings.length) return;
				const [item] = siblings.splice(index, 1);
				siblings.splice(nextIndex, 0, item);
			});
		});
	}

	function updateRule(ruleId: string, patch: Partial<SortingProfileRule>) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => Object.assign(rule, patch));
		});
	}

	function addCondition(ruleId: string) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				rule.conditions.push({ id: crypto.randomUUID(), field: 'part_num', op: 'eq', value: '' });
			});
		});
	}

	function updateCondition(ruleId: string, conditionId: string, patch: Record<string, unknown>) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				rule.conditions = rule.conditions.map((c) => c.id === conditionId ? { ...c, ...patch } : c);
			});
		});
	}

	function deleteCondition(ruleId: string, conditionId: string) {
		withRules((rules) => {
			updateRuleList(rules, ruleId, (rule) => {
				rule.conditions = rule.conditions.filter((c) => c.id !== conditionId);
			});
		});
	}

	function updateFallbackMode<K extends keyof SortingProfileFallbackMode>(key: K, value: boolean) {
		workingFallbackMode = { ...workingFallbackMode, [key]: value };
	}

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
			try { return JSON.parse(trimmed); } catch { return trimmed; }
		}
		if (trimmed === 'true') return true;
		if (trimmed === 'false') return false;
		if (!Number.isNaN(Number(trimmed)) && trimmed !== '') return Number(trimmed);
		return trimmed;
	}

	function toggleNode(ruleId: string) {
		const next = new Set(expandedNodes);
		if (next.has(ruleId)) next.delete(ruleId); else next.add(ruleId);
		expandedNodes = next;
	}

	function selectRule(ruleId: string) {
		selectedRuleId = ruleId;
	}

	function liveRuleForRender(rule: SortingProfileRule): SortingProfileRule {
		return findRule(displayRules, rule.id) ?? rule;
	}

	function profileDocument() {
		return {
			name: profile?.name ?? '',
			description: profile?.description ?? null,
			default_category_id: workingDefaultCategoryId,
			rules: workingRules,
			fallback_mode: workingFallbackMode
		};
	}

	// --- Rule preview ---
	async function loadRulePreview(ruleId: string) {
		if (findRule(workingRules, ruleId)?.rule_type === 'set') {
			rulePreview = null;
			return;
		}
		rulePreviewLoading = true;
		try {
			rulePreview = (await api.previewSortingRule(profileDocument(), { rule_id: ruleId, limit: 5 })) as RulePreviewResult;
		} catch { rulePreview = null; }
		finally { rulePreviewLoading = false; }
	}

	async function loadMorePreview() {
		if (!selectedRuleId) return;
		if (selectedRule?.rule_type === 'set') return;
		rulePreviewLoading = true;
		try {
			rulePreview = (await api.previewSortingRule(profileDocument(), { rule_id: selectedRuleId, limit: 25 })) as RulePreviewResult;
			rulePreviewExpanded = true;
		} catch { /* keep existing */ }
		finally { rulePreviewLoading = false; }
	}

	// --- Save ---
	let suggestingNote = $state(false);

	async function openSavePopover() {
		changeNote = '';
		showSavePopover = true;
		suggestingNote = false;

		if (!profile) return;
		if (!hasOpenRouter) return;
		const oldRules = JSON.parse(originalRulesJson || '[]') as SortingProfileRule[];
		const newRules = $state.snapshot(workingRules) as SortingProfileRule[];
		const rulesChanged = JSON.stringify(oldRules) !== JSON.stringify(newRules);
		if (!rulesChanged) return;

		suggestingNote = true;
		try {
			const result = await api.suggestChangeNote(profile.id, { old_rules: oldRules, new_rules: newRules });
			if (showSavePopover && !changeNote) {
				changeNote = result.change_note;
			}
		} catch (e) {
			console.warn('[Hive] Failed to suggest change note:', e);
		} finally {
			suggestingNote = false;
		}
	}

	function closeSavePopover() { showSavePopover = false; }

	async function saveVersion() {
		if (!profile) return;
		savingVersion = true;
		error = null;
		try {
			const version = await api.saveSortingProfileVersion(profile.id, {
				name: profile.name,
				description: profile.description ?? null,
				default_category_id: workingDefaultCategoryId,
				rules: workingRules,
				fallback_mode: workingFallbackMode,
				change_note: changeNote || null
			});
			success = `Saved version ${version.version_number}.`;
			showSavePopover = false;
			changeNote = '';
			lastLoadedProfileId = '';
			await loadProfile();
		} catch (e: any) {
			error = e.error || 'Failed to save version';
		} finally {
			savingVersion = false;
		}
	}

	async function restoreVersion(versionId: string) {
		if (!profile) return;
		restoringVersionId = versionId;
		error = null;
		try {
			const oldDetail = await api.getSortingProfile(profile.id, versionId);
			const oldVersion = oldDetail.current_version;
			if (!oldVersion) throw new Error('Version not found');
			await api.saveSortingProfileVersion(profile.id, {
				name: oldVersion.name,
				description: oldVersion.description ?? null,
				default_category_id: oldVersion.default_category_id,
				rules: oldVersion.rules,
				fallback_mode: oldVersion.fallback_mode,
				change_note: `Restored from v${oldVersion.version_number}`
			});
			lastLoadedProfileId = '';
			await loadProfile();
			rightTab = 'chat';
		} catch (e: any) {
			error = e.error || e.message || 'Failed to restore version';
		} finally {
			restoringVersionId = null;
		}
	}

	async function viewVersion(versionId: string) {
		if (!profile) return;
		previewLoading = true;
		try {
			const detail = await api.getSortingProfile(profile.id, versionId);
			previewVersion = detail.current_version;
		} catch (e: any) {
			error = e.error || 'Failed to load version';
		} finally {
			previewLoading = false;
		}
	}

	function exitPreview() {
		previewVersion = null;
	}

	async function forkFromVersion(versionId: string) {
		if (!profile) return;
		error = null;
		try {
			const fork = await api.forkSortingProfile(profile.id, { add_to_library: true }, versionId);
			window.location.href = `/profiles/${fork.id}/edit`;
		} catch (e: any) {
			error = e.error || 'Failed to fork';
		}
	}

	const displayRules = $derived(previewVersion ? previewVersion.rules : workingRules);
	const isPreview = $derived(previewVersion !== null);

	function formatDate(iso: string): string {
		const d = new Date(iso);
		return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' })
			+ ' ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}

	// --- AI ---
	async function sendAiMessage() {
		if (!profile || !aiMessage.trim()) return;
		const userMsg = aiMessage.trim();
		aiMessage = '';

		// Show user message immediately
		const tempUserMsg: SortingProfileAiMessage = {
			id: crypto.randomUUID(),
			role: 'user',
			content: userMsg,
			model: null,
			version_id: profile.current_version?.id ?? null,
			applied_version_id: null,
			selected_rule_id: selectedRuleId,
			usage: null,
			proposal: null,
			tool_trace: [],
			applied_at: null,
			created_at: new Date().toISOString()
		};
		aiMessages = [...aiMessages, tempUserMsg];

		aiBusy = true;
		aiProgress = [{ type: 'thinking' }];
		error = null;
		try {
			let response: SortingProfileAiMessage;
			try {
				// Try streaming endpoint for live progress
				response = await api.streamSortingProfileAiMessage(
					profile.id,
					{
						message: userMsg,
						version_id: profile.current_version?.id ?? null,
						selected_rule_id: selectedRuleId
					},
					(event) => {
						aiProgress = [...aiProgress, event as typeof aiProgress[number]];
					}
				);
			} catch {
				// Fallback to non-streaming endpoint
				aiProgress = [{ type: 'thinking' }];
				response = await api.createSortingProfileAiMessage(profile.id, {
					message: userMsg,
					version_id: profile.current_version?.id ?? null,
					selected_rule_id: selectedRuleId
				});
			}
			aiMessages = [...aiMessages, response];

			// Auto-apply if the AI returned a proposal with actual operations
			const proposals = response.proposal && Array.isArray((response.proposal as any).proposals)
				? (response.proposal as any).proposals as unknown[]
				: [];
			if (proposals.length > 0) {
				aiProgress = [...aiProgress, { type: 'applying' }];
				const version = await api.applySortingProfileAiMessage(profile.id, response.id, {});
				const idx = aiMessages.findIndex((m) => m.id === response.id);
				if (idx >= 0) {
					aiMessages[idx] = { ...aiMessages[idx], applied_at: new Date().toISOString() };
				}
				lastLoadedProfileId = '';
				await loadProfile();
			}
		} catch (e: any) {
			error = e.error || e.message || 'Request failed';
		} finally {
			aiBusy = false;
			aiProgress = [];
		}
	}

	// --- Part count helper ---
	function getPartCount(ruleId: string): number | null {
		const stats = perCategoryStats[ruleId];
		if (!stats || stats.parts === undefined) return null;
		return stats.parts;
	}

	function formatPartCount(count: number | null): string {
		if (count === null) return '';
		if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
		return String(count);
	}

	function conditionSummary(rule: SortingProfileRule): string {
		if (rule.rule_type === 'set') {
			if (isCustomSetRule(rule)) {
				return `Custom set · ${customSetPartsLabel(rule)}`;
			}
			const meta = rule.set_meta;
			if (meta) return `${rule.set_num} · ${meta.year} · ${meta.num_parts} parts`;
			return rule.set_num || 'LEGO Set';
		}
		if (rule.conditions.length === 0) return 'No conditions';
		return rule.conditions
			.map((c) => {
				const op = opLabels[c.op] ?? c.op;
				const val = typeof c.value === 'string' ? c.value : JSON.stringify(c.value);
				const short = val.length > 20 ? val.slice(0, 20) + '…' : val;
				return `${c.field} ${op} ${short}`;
			})
			.join(' · ');
	}

	function dismissSuccess() { success = null; }

	function isToolResultExpanded(key: string): boolean {
		return expandedToolResults.has(key);
	}

	function toggleToolResult(key: string): void {
		const next = new Set(expandedToolResults);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		expandedToolResults = next;
	}

	function visibleToolResultItems(result: ExpandableToolResult, key: string): ToolResultListItem[] {
		if (isToolResultExpanded(key)) return result.items;
		return result.items.slice(0, TOOL_RESULT_COLLAPSED_COUNT);
	}

	function canExpandToolResult(result: ExpandableToolResult): boolean {
		return result.items.length > TOOL_RESULT_COLLAPSED_COUNT;
	}
</script>

<svelte:head>
	<title>{profile ? `Edit ${profile.name} - Hive` : 'Edit Profile - Hive'}</title>
</svelte:head>

{#if loading}
	<Spinner />
{:else if !profile}
	<Alert variant="danger">Profile not found.</Alert>
{:else if !profile.current_version}
	<Alert variant="danger">No version available.</Alert>
{:else}
	<!-- Header -->
	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href={`/profiles/${profile.id}`} class="text-text-muted hover:text-text" title="Back to profile">
				<svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
				</svg>
			</a>
			<div>
				<input
					type="text"
					value={profile.name}
					onblur={async (e) => {
						const newName = (e.currentTarget as HTMLInputElement).value.trim();
						if (newName && newName !== profile!.name) {
							try {
								const updated = await api.updateSortingProfile(profile!.id, { name: newName });
								profile = updated;
							} catch { /* ignore */ }
						}
					}}
					onkeydown={(e) => { if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur(); }}
					class="border-0 bg-transparent text-xl font-bold text-text outline-none focus:border-b-2 focus:border-primary w-full"
				/>
				<span class="text-xs text-text-muted">v{profile.current_version.version_number}</span>
			</div>
		</div>
		<div class="relative">
			<Button onclick={openSavePopover} disabled={savingVersion}>Save</Button>
			{#if showSavePopover}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="fixed inset-0 z-40" onclick={closeSavePopover} onkeydown={(e) => { if (e.key === 'Escape') closeSavePopover(); }}></div>
				<div class="absolute right-0 top-full z-50 mt-2 w-72 border border-border bg-white p-4">
					<h3 class="mb-2 text-sm font-semibold text-text">Save New Version</h3>
					<label class="mb-1 block text-xs text-text-muted" for="save-note">What changed? (optional)</label>
					<div class="relative mb-3">
						<input id="save-note" type="text" bind:value={changeNote} placeholder={suggestingNote ? 'Generating...' : 'e.g. Added gear categories'}
							class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary {suggestingNote ? 'pr-8' : ''}"
							onkeydown={(e) => { if (e.key === 'Enter') void saveVersion(); }} />
						{#if suggestingNote}
							<div class="absolute right-2.5 top-1/2 -translate-y-1/2">
								<div class="h-3.5 w-3.5 animate-spin border-2 border-border border-t-[#7A7770]" style="border-radius: 50%"></div>
							</div>
						{/if}
					</div>
					<div class="flex justify-end gap-2">
						<Button variant="secondary" size="sm" onclick={closeSavePopover}>Cancel</Button>
						<Button size="sm" onclick={() => void saveVersion()} disabled={savingVersion} loading={savingVersion}>
							{savingVersion ? 'Saving...' : 'Save'}
						</Button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if error}
		<div class="mb-3"><Alert variant="danger">{error}</Alert></div>
	{/if}
	{#if success}
		<div class="mb-3 flex items-center justify-between gap-2">
			<div class="flex-1"><Alert variant="success">{success}</Alert></div>
			<button onclick={dismissSuccess} class="text-success hover:text-success" aria-label="Dismiss">
				<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
				</svg>
			</button>
		</div>
	{/if}

	<!-- Main 2-column layout: Rules (left, wider) | Chat (right) -->
	<div class="grid min-h-0 grid-cols-1 gap-4 overflow-hidden xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]" style="height: calc(100vh - 200px);">

		<!-- LEFT: Rules (accordion) -->
		<div class="flex min-h-0 min-w-0 flex-col border border-border bg-white">
			<div class="flex items-center justify-between border-b border-border px-4 py-2">
				<h2 class="text-sm font-semibold text-text">Rules</h2>
				{#if !isPreview}
					<div class="flex items-center gap-1.5">
						<button onclick={() => addRule()}
							class="border border-border bg-white px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-bg hover:text-text">
							+ Rule
						</button>
						<button onclick={() => { showSetSearch = true; }}
							class="border border-border bg-white px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-bg hover:text-text">
							+ Set
						</button>
						<button onclick={addCustomSetRule}
							class="border border-border bg-white px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-bg hover:text-text">
							+ Custom Set
						</button>
					</div>
				{/if}
			</div>
			{#if isPreview}
				<div class="flex items-center justify-between border-b border-warning/30 bg-warning/[0.1] px-4 py-2">
					<span class="text-xs font-medium text-[#A16207]">
						Viewing v{previewVersion?.version_number}
						{#if previewVersion?.change_note}
							— {previewVersion.change_note}
						{/if}
					</span>
					<div class="flex gap-2">
						<button onclick={() => { if (previewVersion) void restoreVersion(previewVersion.id); }}
							disabled={restoringVersionId !== null}
							class="bg-primary px-2 py-1 text-xs font-medium text-white hover:bg-primary-hover disabled:opacity-50">
							{restoringVersionId ? 'Restoring...' : 'Restore'}
						</button>
						<button onclick={exitPreview}
							class="border border-border px-2 py-1 text-xs font-medium text-text-muted hover:bg-bg">
							Back
						</button>
					</div>
				</div>
			{/if}
			<div class="flex-1 overflow-y-auto">
				{#if previewLoading}
					<div class="flex items-center justify-center p-8"><Spinner /></div>
				{:else if displayRules.length === 0}
					<div class="p-4 text-center text-sm text-text-muted">
						No rules yet. Use chat to generate categories, or add one manually.
					</div>
				{:else}
					{#each displayRules as rule (rule.id)}
						<RuleAccordionNode
							{rule}
							depth={0}
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
							onToggleNode={toggleNode}
							onSelectRule={selectRule}
							onMoveRule={moveRule}
							onDeleteRule={deleteRule}
							onUpdateRule={updateRule}
							onAddRule={addRule}
							onAddCondition={addCondition}
							onUpdateCondition={updateCondition}
							onDeleteCondition={deleteCondition}
							onUpdateCustomSetName={updateCustomSetName}
							onOpenBrickLinkCsvImport={openBrickLinkCsvImport}
							onEnsureCatalogColorsLoaded={() => void ensureCatalogColorsLoaded()}
							onSetAddingPartForRule={(id) => { addingPartForRule = id; }}
							onAddCustomSetPart={addCustomSetPart}
							onUpdateCustomSetPart={updateCustomSetPart}
							onRemoveCustomSetPart={removeCustomSetPart}
							onSetChangingSetForRule={(id) => { changingSetForRule = id; }}
							onSetRule={(ruleId, set) => {
								updateRule(ruleId, {
									set_source: 'rebrickable',
									set_num: set.set_num,
									name: set.name,
									custom_parts: [],
									set_meta: { name: set.name, year: set.year, num_parts: set.num_parts, img_url: set.img_url }
								} as Partial<SortingProfileRule>);
								changingSetForRule = null;
							}}
							onLoadMorePreview={loadMorePreview}
						/>
					{/each}
				{/if}
			</div>
			{#if !isPreview && showSetSearch}
			<div class="border-t border-border px-3 py-2">
				<SetSearch onSelect={addSetRule} onCancel={() => { showSetSearch = false; }} />
			</div>
			{/if}
			<!-- Fallback UI hidden for now — re-add later when the concept is clearer -->
		</div>

		<ProfileChatPanel
			{profile}
			{rightTab}
			onRightTabChange={(tab) => { rightTab = tab; }}
			{hasOpenRouter}
			{aiMessages}
			{aiMessage}
			onAiMessageChange={(value) => { aiMessage = value; }}
			{aiBusy}
			{isNewProfile}
			workingRulesLength={workingRules.length}
			{visibleAiProgressCards}
			chatContainerRef={(el) => { chatContainer = el; }}
			onSendAiMessage={() => void sendAiMessage()}
			onViewVersion={(id) => void viewVersion(id)}
			onRestoreVersion={(id) => void restoreVersion(id)}
			onForkFromVersion={(id) => void forkFromVersion(id)}
			onExitPreview={exitPreview}
			{restoringVersionId}
			{previewLoading}
			{formatDate}
			{formatDuration}
			{displayAiMessageContent}
			{aiMessagePerformanceLabel}
			{proposalActionSummaries}
			{toolTraceTitle}
			{getExpandableToolResult}
			{getToolResultSummaryLine}
			{visibleToolResultItems}
			{canExpandToolResult}
			{isToolResultExpanded}
			onToggleToolResult={toggleToolResult}
		/>
	</div>

	<!-- Sticky bottom bar -->
	{#if hasUnsavedChanges}
		<div class="fixed bottom-0 left-0 right-0 z-30 border-t border-border bg-white px-4 py-3">
			<div class="mx-auto flex max-w-7xl items-center justify-between">
				<div class="flex items-center gap-2 text-sm text-text-muted">
					<span class="inline-block h-2 w-2 bg-warning"></span>
					Unsaved changes
				</div>
				<Button onclick={openSavePopover} disabled={savingVersion}>Save</Button>
			</div>
		</div>
		<div class="h-16"></div>
	{/if}
{/if}

<input
	bind:this={csvImportFileInput}
	type="file"
	accept=".csv,text/csv"
	class="hidden"
	onchange={handleBrickLinkCsvSelected}
/>
