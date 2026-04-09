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
	import { renderMarkdown } from '$lib/markdown';

	const ANY_COLOR_ID = -1;

	type RulePreviewResult = {
		total: number;
		sample: Array<Record<string, unknown>>;
		offset: number;
		limit: number;
	};

	type AiProgressEvent = {
		type: string;
		tool?: string;
		input?: Record<string, unknown>;
		output_summary?: string;
		output?: Record<string, unknown> | null;
		duration_ms?: number;
	};

	type ToolResultListItem = {
		id: string;
		primary: string;
		secondary: string | null;
		imageUrl?: string | null;
	};

	type ExpandableToolResult = {
		layout: 'list' | 'media-grid';
		total: number;
		availableCount: number;
		singularLabel: string;
		pluralLabel: string;
		emptyMessage: string;
		items: ToolResultListItem[];
	};

	type AiProgressCard = {
		id: string;
		kind: 'analysis' | 'tool' | 'writing' | 'applying';
		status: 'active' | 'complete';
		title: string;
		detail: string | null;
		tool?: string;
		output?: Record<string, unknown> | null;
		durationMs?: number | null;
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

	function searchScopeSuffix(input: Record<string, unknown> | undefined): string {
		if (!input) return '';
		const minYear = typeof input.min_year === 'number' ? input.min_year : null;
		const maxYear = typeof input.max_year === 'number' ? input.max_year : null;
		if (minYear && maxYear && minYear === maxYear) return ` from ${minYear}`;
		if (minYear && maxYear) return ` from ${minYear} to ${maxYear}`;
		if (minYear) return ` from ${minYear} or newer`;
		if (maxYear) return ` up to ${maxYear}`;
		return '';
	}

	function toolSearchSubject(tool: string | undefined, input: Record<string, unknown> | undefined): string {
		const query = typeof input?.query === 'string' && input.query.trim() ? input.query.trim() : 'your query';
		if (tool === 'search_sets') return `LEGO sets matching "${query}"${searchScopeSuffix(input)}`;
		if (tool === 'search_parts') return `LEGO parts matching "${query}"`;
		if (tool === 'get_set_inventory') {
			const setNum = typeof input?.set_num === 'string' && input.set_num.trim() ? input.set_num.trim() : 'that set';
			return `pieces in LEGO set "${setNum}"`;
		}
		return 'catalog data';
	}

	function toolStageTitle(
		tool: string | undefined,
		input: Record<string, unknown> | undefined,
		status: 'active' | 'complete'
	): string {
		const prefix = status === 'active' ? 'Checking' : 'Checked';
		return `${prefix} ${toolSearchSubject(tool, input)}`;
	}

	function toolActiveDetail(tool: string | undefined, input: Record<string, unknown> | undefined): string {
		if (tool === 'search_sets') {
			const scope = searchScopeSuffix(input);
			return scope
				? `I am looking through the set catalog${scope} now.`
				: 'I am looking through the set catalog now.';
		}
		if (tool === 'search_parts') {
			return 'I am checking the parts catalog for matching pieces.';
		}
		if (tool === 'get_set_inventory') {
			return 'I am looking through the set inventory and piece list.';
		}
		return 'I am gathering the information I need.';
	}

	function toolTraceTitle(item: AiToolTraceItem): string {
		return toolStageTitle(item.tool, item.input, 'complete');
	}

	function formatDuration(ms: number | null | undefined): string | null {
		if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null;
		if (ms >= 60000) return `${(ms / 60000).toFixed(1)} min`;
		if (ms >= 10000) return `${Math.round(ms / 1000)} s`;
		if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
		return `${Math.round(ms)} ms`;
	}

	function aiMessagePerformance(message: SortingProfileAiMessage): {
		totalMs: number | null;
		llmMs: number | null;
		toolMs: number | null;
		roundCount: number | null;
		toolCallCount: number | null;
	} | null {
		const performance = message.usage?.performance;
		if (!isRecord(performance)) return null;
		const totalMs = asNumber(performance.total_ms);
		const llmMs = asNumber(performance.llm_ms);
		const toolMs = asNumber(performance.tool_ms);
		const roundCount = asNumber(performance.round_count);
		const toolCallCount = asNumber(performance.tool_call_count);
		if (totalMs === null && llmMs === null && toolMs === null) return null;
		return { totalMs, llmMs, toolMs, roundCount, toolCallCount };
	}

	function aiMessagePerformanceLabel(message: SortingProfileAiMessage): string | null {
		const perf = aiMessagePerformance(message);
		if (!perf) return null;
		const parts: string[] = [];
		const total = formatDuration(perf.totalMs);
		const llm = formatDuration(perf.llmMs);
		const tool = formatDuration(perf.toolMs);
		if (total) parts.push(`Total ${total}`);
		if (llm) parts.push(`Model ${llm}`);
		if (tool && perf.toolMs && perf.toolMs > 0) parts.push(`Tools ${tool}`);
		if (typeof perf.roundCount === 'number' && perf.roundCount > 1) parts.push(`${perf.roundCount} rounds`);
		if (typeof perf.toolCallCount === 'number' && perf.toolCallCount > 0) parts.push(`${perf.toolCallCount} tool calls`);
		return parts.length > 0 ? parts.join(' · ') : null;
	}

		function isRecord(value: unknown): value is Record<string, unknown> {
			return typeof value === 'object' && value !== null;
		}

		function asNumber(value: unknown): number | null {
			return typeof value === 'number' && Number.isFinite(value) ? value : null;
		}

		function asString(value: unknown): string | null {
			return typeof value === 'string' && value.trim() ? value.trim() : null;
		}

		function formatToolResultCount(result: ExpandableToolResult): string {
			const label = result.total === 1 ? result.singularLabel : result.pluralLabel;
			return `${result.total} ${label}`;
		}

		function getToolResultSummaryLine(result: ExpandableToolResult): string {
			if (result.total === 0) return result.emptyMessage;
			if (result.availableCount < result.total) {
				return `Showing ${result.availableCount} of ${formatToolResultCount(result)} returned by the search.`;
			}
			return `Found ${formatToolResultCount(result)}.`;
		}

		function buildSetToolResult(output: Record<string, unknown>): ExpandableToolResult | null {
			const rawSets = Array.isArray(output.sets) ? output.sets.filter(isRecord) : [];
			const items = rawSets.map((legoSet, index) => {
				const name = asString(legoSet.name) ?? 'Unnamed set';
				const partCount = asNumber(legoSet.num_parts);
				const badges = [
					asString(legoSet.set_num),
					asNumber(legoSet.year)?.toString() ?? null,
					partCount !== null ? `${partCount} parts` : null
				].filter((value): value is string => Boolean(value));
				return {
					id: asString(legoSet.set_num) ?? `set-${index}`,
					primary: name,
					secondary: badges.length > 0 ? badges.join(' · ') : null,
					imageUrl: asString(legoSet.img_url) ?? asString(legoSet.set_img_url)
				};
			});
			const total = asNumber(output.total) ?? items.length;
			return {
				layout: 'media-grid',
				total,
				availableCount: items.length,
				singularLabel: 'set',
				pluralLabel: 'sets',
				emptyMessage: 'No sets found.',
				items
			};
		}

		function buildPartToolResult(output: Record<string, unknown>): ExpandableToolResult | null {
			const rawParts = Array.isArray(output.parts) ? output.parts.filter(isRecord) : [];
			const items = rawParts.map((part, index) => {
				const name = asString(part.name) ?? 'Unnamed part';
				const bits = [
					asString(part.part_num),
					asString(part.category),
					asString(part.years)
				].filter(Boolean);
				return {
					id: asString(part.part_num) ?? `part-${index}`,
					primary: name,
					secondary: bits.length > 0 ? bits.join(' · ') : null
				};
			});
			const total = asNumber(output.total) ?? items.length;
			return {
				layout: 'list',
				total,
				availableCount: items.length,
				singularLabel: 'part',
				pluralLabel: 'parts',
				emptyMessage: 'No parts found.',
				items
			};
		}

		function buildSetInventoryToolResult(output: Record<string, unknown>): ExpandableToolResult | null {
			const rawInventory = Array.isArray(output.inventory) ? output.inventory.filter(isRecord) : [];
			const items = rawInventory.map((part, index) => {
				const name = asString(part.part_name) ?? asString(part.part_num) ?? 'Unnamed part';
				const bits = [
					asString(part.part_num),
					asString(part.color_name) ?? (asNumber(part.color_id)?.toString() ?? null),
					asNumber(part.quantity) !== null ? `qty ${asNumber(part.quantity)}` : null,
					part.is_spare ? 'spare' : null
				].filter(Boolean);
				return {
					id: `${asString(part.part_num) ?? 'part'}-${asString(part.color_name) ?? asNumber(part.color_id) ?? index}-${index}`,
					primary: name,
					secondary: bits.length > 0 ? bits.join(' · ') : null,
					imageUrl: asString(part.img_url)
				};
			});
			const total = asNumber(output.total) ?? items.length;
			return {
				layout: 'media-grid',
				total,
				availableCount: items.length,
				singularLabel: 'inventory entry',
				pluralLabel: 'inventory entries',
				emptyMessage: 'No inventory entries found.',
				items
			};
		}

		function getExpandableToolResult(
			tool: string | undefined,
			output: Record<string, unknown> | null | undefined
		): ExpandableToolResult | null {
			if (!output) return null;
			if (tool === 'search_sets') return buildSetToolResult(output);
			if (tool === 'search_parts') return buildPartToolResult(output);
			if (tool === 'get_set_inventory') return buildSetInventoryToolResult(output);
			return null;
		}

		const TOOL_RESULT_COLLAPSED_COUNT = 5;

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

	function parseEmbeddedProposal(content: string): Record<string, unknown> | null {
		const trimmed = content.trim();
		if (!trimmed) return null;

		const candidates: string[] = [trimmed];
		const fencedMatches = trimmed.matchAll(/```(?:json)?\s*([\s\S]*?)```/gi);
		for (const match of fencedMatches) {
			const candidate = match[1]?.trim();
			if (candidate) candidates.push(candidate);
		}

		const unterminatedFence = trimmed.match(/```(?:json)?\s*([\s\S]*)$/i);
		if (unterminatedFence?.[1]?.trim()) {
			candidates.push(unterminatedFence[1].trim());
		}

		for (const candidate of candidates) {
			try {
				const parsed = JSON.parse(candidate);
				if (parsed && typeof parsed === 'object') {
					return parsed as Record<string, unknown>;
				}
			} catch {
				// ignore candidate
			}
		}

		return null;
	}

	function displayAiMessageContent(content: string): string {
		const parsed = parseEmbeddedProposal(content);
		const summary = typeof parsed?.summary === 'string' ? parsed.summary.trim() : '';
		const contentWithoutJsonFence = content
			.replace(/```(?:json)?\s*[\s\S]*?```/gi, '')
			.replace(/```(?:json)?\s*[\s\S]*$/gi, '')
			.trim();

		if (summary && (!contentWithoutJsonFence || content.trim().startsWith('{'))) {
			return summary;
		}

		if (contentWithoutJsonFence) {
			return contentWithoutJsonFence;
		}

		return summary || content;
	}

	function buildAiProgressCards(events: AiProgressEvent[]): AiProgressCard[] {
		const cards: AiProgressCard[] = [];
		let counter = 0;

		function completeActiveAnalysis(nextTitle: string) {
			const card = [...cards].reverse().find((entry) => entry.kind === 'analysis' && entry.status === 'active');
			if (!card) return;
			card.status = 'complete';
			card.title = nextTitle;
		}

		for (const event of events) {
			if (event.type === 'thinking') {
				const hasCompletedTool = cards.some((card) => card.kind === 'tool' && card.status === 'complete');
				const activeAnalysis = [...cards].reverse().find(
					(card) => card.kind === 'analysis' && card.status === 'active'
				);
				const title = hasCompletedTool ? 'Reviewing the matches' : 'Understanding your request';
				const detail = hasCompletedTool
					? 'I am deciding which results fit what you asked for.'
					: 'I am figuring out what should be added or changed.';
				if (activeAnalysis) {
					activeAnalysis.title = title;
					activeAnalysis.detail = detail;
				} else {
					cards.push({
						id: `analysis-${counter++}`,
						kind: 'analysis',
						status: 'active',
						title,
						detail
					});
				}
				continue;
			}

			if (event.type === 'tool_call') {
				completeActiveAnalysis('Request understood');
					cards.push({
						id: `tool-${counter++}`,
						kind: 'tool',
						status: 'active',
						title: toolStageTitle(event.tool, event.input, 'active'),
						detail: toolActiveDetail(event.tool, event.input),
						tool: event.tool,
						output: null,
						durationMs: null
					});
					continue;
				}

			if (event.type === 'tool_result') {
				const activeTool = cards.find(
					(card) => card.kind === 'tool' && card.status === 'active' && card.tool === event.tool
				);
					if (activeTool) {
						activeTool.status = 'complete';
						activeTool.title = toolStageTitle(event.tool, event.input, 'complete');
						activeTool.detail = event.output_summary ?? 'Done.';
						activeTool.output = event.output ?? null;
						activeTool.durationMs = event.duration_ms ?? null;
					} else {
						cards.push({
							id: `tool-${counter++}`,
							kind: 'tool',
							status: 'complete',
							title: toolStageTitle(event.tool, event.input, 'complete'),
							detail: event.output_summary ?? 'Done.',
							tool: event.tool,
							output: event.output ?? null,
							durationMs: event.duration_ms ?? null
						});
					}
				continue;
			}

			if (event.type === 'generating') {
				completeActiveAnalysis('Results reviewed');
				const activeWriting = [...cards].reverse().find(
					(card) => card.kind === 'writing' && card.status === 'active'
				);
				if (!activeWriting) {
					cards.push({
						id: `writing-${counter++}`,
						kind: 'writing',
						status: 'active',
						title: 'Preparing the update',
						detail: 'I am turning that into clear rule changes.'
					});
				}
				continue;
			}

			if (event.type === 'applying') {
				const activeWriting = [...cards].reverse().find(
					(card) => card.kind === 'writing' && card.status === 'active'
				);
				if (activeWriting) {
					activeWriting.status = 'complete';
					activeWriting.title = 'Update prepared';
				}
				const activeApplying = [...cards].reverse().find(
					(card) => card.kind === 'applying' && card.status === 'active'
				);
				if (!activeApplying) {
					cards.push({
						id: `applying-${counter++}`,
						kind: 'applying',
						status: 'active',
						title: 'Saving the changes',
						detail: 'I am updating the profile now.'
					});
				}
			}
		}

		return cards;
	}

	function proposalActionSummaries(proposal: Record<string, unknown> | null): string[] {
		if (!proposal) return [];
		const proposals = proposal.proposals;
		if (!Array.isArray(proposals)) return [];
		return proposals.map((p: Record<string, unknown>) => {
			const action = p.action as string;
			const name = (p.name as string) || 'rule';
			if (action === 'create') return `Created "${name}"`;
			if (action === 'create_set') return `Added set "${name}"`;
			if (action === 'edit') return `Edited "${name}"`;
			if (action === 'move') return `Moved "${name}"`;
			if (action === 'delete') return `Deleted "${name}"`;
			return `${action} "${name}"`;
		});
	}
</script>

<svelte:head>
	<title>{profile ? `Edit ${profile.name} - Hive` : 'Edit Profile - Hive'}</title>
</svelte:head>

{#if loading}
	<Spinner />
{:else if !profile}
	<div class="bg-[#D01012]/8 p-4 text-sm text-[#D01012]">Profile not found.</div>
{:else if !profile.current_version}
	<div class="bg-[#D01012]/8 p-4 text-sm text-[#D01012]">No version available.</div>
{:else}
	<!-- Header -->
	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href={`/profiles/${profile.id}`} class="text-[#7A7770] hover:text-[#1A1A1A]" title="Back to profile">
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
					class="border-0 bg-transparent text-xl font-bold text-[#1A1A1A] outline-none focus:border-b-2 focus:border-[#D01012] w-full"
				/>
				<span class="text-xs text-[#7A7770]">v{profile.current_version.version_number}</span>
			</div>
		</div>
		<div class="relative">
			<button onclick={openSavePopover} disabled={savingVersion}
				class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50">
				Save
			</button>
			{#if showSavePopover}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="fixed inset-0 z-40" onclick={closeSavePopover} onkeydown={(e) => { if (e.key === 'Escape') closeSavePopover(); }}></div>
				<div class="absolute right-0 top-full z-50 mt-2 w-72 border border-[#E2E0DB] bg-white p-4">
					<h3 class="mb-2 text-sm font-semibold text-[#1A1A1A]">Save New Version</h3>
					<label class="mb-1 block text-xs text-[#7A7770]" for="save-note">What changed? (optional)</label>
					<div class="relative mb-3">
						<input id="save-note" type="text" bind:value={changeNote} placeholder={suggestingNote ? 'Generating...' : 'e.g. Added gear categories'}
							class="w-full border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012] {suggestingNote ? 'pr-8' : ''}"
							onkeydown={(e) => { if (e.key === 'Enter') void saveVersion(); }} />
						{#if suggestingNote}
							<div class="absolute right-2.5 top-1/2 -translate-y-1/2">
								<div class="h-3.5 w-3.5 animate-spin border-2 border-[#E2E0DB] border-t-[#7A7770]" style="border-radius: 50%"></div>
							</div>
						{/if}
					</div>
					<div class="flex justify-end gap-2">
						<button onclick={closeSavePopover} class="border border-[#E2E0DB] px-3 py-1.5 text-xs font-medium text-[#1A1A1A] hover:bg-[#F7F6F3]">Cancel</button>
						<button onclick={() => void saveVersion()} disabled={savingVersion}
							class="bg-[#D01012] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#B00E10] disabled:opacity-50">
							{savingVersion ? 'Saving...' : 'Save'}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if error}
		<div class="mb-3 bg-[#D01012]/8 p-3 text-sm text-[#D01012]">{error}</div>
	{/if}
	{#if success}
		<div class="mb-3 flex items-center justify-between bg-[#00852B]/10 p-3 text-sm text-[#00852B]">
			<span>{success}</span>
			<button onclick={dismissSuccess} class="text-[#00852B] hover:text-[#00852B]" aria-label="Dismiss">
				<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
				</svg>
			</button>
		</div>
	{/if}

	<!-- Main 2-column layout: Rules (left, wider) | Chat (right) -->
	<div class="grid min-h-0 grid-cols-1 gap-4 overflow-hidden xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]" style="height: calc(100vh - 200px);">

		<!-- LEFT: Rules (accordion) -->
		<div class="flex min-h-0 min-w-0 flex-col border border-[#E2E0DB] bg-white">
			<div class="flex items-center justify-between border-b border-[#E2E0DB] px-4 py-2">
				<h2 class="text-sm font-semibold text-[#1A1A1A]">Rules</h2>
				{#if !isPreview}
					<div class="flex items-center gap-1.5">
						<button onclick={() => addRule()}
							class="border border-[#E2E0DB] bg-white px-2.5 py-1 text-[11px] font-medium text-[#7A7770] hover:bg-[#F7F6F3] hover:text-[#1A1A1A]">
							+ Rule
						</button>
						<button onclick={() => { showSetSearch = true; }}
							class="border border-[#E2E0DB] bg-white px-2.5 py-1 text-[11px] font-medium text-[#7A7770] hover:bg-[#F7F6F3] hover:text-[#1A1A1A]">
							+ Set
						</button>
						<button onclick={addCustomSetRule}
							class="border border-[#E2E0DB] bg-white px-2.5 py-1 text-[11px] font-medium text-[#7A7770] hover:bg-[#F7F6F3] hover:text-[#1A1A1A]">
							+ Custom Set
						</button>
					</div>
				{/if}
			</div>
			{#if isPreview}
				<div class="flex items-center justify-between border-b border-[#FFD500]/30 bg-[#FFFBEB] px-4 py-2">
					<span class="text-xs font-medium text-[#A16207]">
						Viewing v{previewVersion?.version_number}
						{#if previewVersion?.change_note}
							— {previewVersion.change_note}
						{/if}
					</span>
					<div class="flex gap-2">
						<button onclick={() => { if (previewVersion) void restoreVersion(previewVersion.id); }}
							disabled={restoringVersionId !== null}
							class="bg-[#D01012] px-2 py-1 text-xs font-medium text-white hover:bg-[#B00E10] disabled:opacity-50">
							{restoringVersionId ? 'Restoring...' : 'Restore'}
						</button>
						<button onclick={exitPreview}
							class="border border-[#E2E0DB] px-2 py-1 text-xs font-medium text-[#7A7770] hover:bg-[#F7F6F3]">
							Back
						</button>
					</div>
				</div>
			{/if}
			<div class="flex-1 overflow-y-auto">
				{#if previewLoading}
					<div class="flex items-center justify-center p-8"><Spinner /></div>
				{:else if displayRules.length === 0}
					<div class="p-4 text-center text-sm text-[#7A7770]">
						No rules yet. Use chat to generate categories, or add one manually.
					</div>
				{:else}
					{#each displayRules as rule (rule.id)}
						{@render accordionNode(rule, 0)}
					{/each}
				{/if}
			</div>
			{#if !isPreview && showSetSearch}
			<div class="border-t border-[#E2E0DB] px-3 py-2">
				<SetSearch onSelect={addSetRule} onCancel={() => { showSetSearch = false; }} />
			</div>
			{/if}
			<!-- Fallback UI hidden for now — re-add later when the concept is clearer -->
		</div>

		<!-- RIGHT: Chat / Versions -->
		<div class="flex min-h-0 min-w-0 flex-col overflow-hidden border border-[#E2E0DB] bg-white">
			<div class="flex border-b border-[#E2E0DB]">
				<button onclick={() => { rightTab = 'chat'; }}
					class="flex-1 px-4 py-2 text-center text-sm font-medium transition-colors
						{rightTab === 'chat' ? 'border-b-2 border-b-[#D01012] text-[#D01012]' : 'text-[#7A7770] hover:text-[#1A1A1A]'}">
					Chat
				</button>
				<button onclick={() => { rightTab = 'versions'; }}
					class="flex-1 px-4 py-2 text-center text-sm font-medium transition-colors
						{rightTab === 'versions' ? 'border-b-2 border-b-[#D01012] text-[#D01012]' : 'text-[#7A7770] hover:text-[#1A1A1A]'}">
					Versions
					<span class="ml-1 text-xs font-normal text-[#7A7770]">· {profile.versions.length}</span>
				</button>
			</div>

			{#if rightTab === 'versions'}
				<!-- Version History -->
				<div class="flex-1 overflow-y-auto">
					{#if profile.versions.length === 0}
						<div class="p-6 text-center text-sm text-[#7A7770]">No versions yet.</div>
					{:else}
						<div class="divide-y divide-[#E2E0DB]">
							{#each [...profile.versions].reverse() as version (version.id)}
								{@const isCurrent = version.id === profile.current_version?.id}
								<div class="px-4 py-3 {isCurrent ? 'bg-[#D01012]/8' : ''}">
									<div class="flex items-center justify-between">
										<div class="flex items-center gap-2">
											{#if isCurrent}
												<span class="inline-block h-2.5 w-2.5 shrink-0 bg-[#D01012]"></span>
											{/if}
											<span class="text-sm font-semibold {isCurrent ? 'text-[#D01012]' : 'text-[#1A1A1A]'}">v{version.version_number}</span>
											{#if isCurrent}
												<span class="bg-[#D01012]/8 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#D01012]">current</span>
											{/if}
											{#if version.is_published}
												<span class="bg-[#00852B]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#00852B]">published</span>
											{/if}
										</div>
										<span class="text-xs text-[#7A7770]">{formatDate(version.created_at)}</span>
									</div>
									{#if version.change_note}
										<p class="mt-1 text-xs text-[#7A7770]">{version.change_note}</p>
									{/if}
									<div class="mt-1 flex items-center gap-3 text-xs text-[#7A7770]">
										<span>{version.compiled_part_count} parts</span>
										{#if version.label}
											<span>{version.label}</span>
										{/if}
									</div>
									<div class="mt-2 flex gap-2">
										<button onclick={() => { if (isCurrent) exitPreview(); else void viewVersion(version.id); }}
											disabled={previewLoading}
											class="border border-[#E2E0DB] px-2 py-1 text-xs font-medium text-[#7A7770] hover:bg-[#F7F6F3] disabled:opacity-50">
											View
										</button>
										{#if !isCurrent}
											<button onclick={() => void restoreVersion(version.id)}
												disabled={restoringVersionId !== null}
												class="border border-[#E2E0DB] px-2 py-1 text-xs font-medium text-[#7A7770] hover:bg-[#F7F6F3] disabled:opacity-50">
												{restoringVersionId === version.id ? 'Restoring...' : 'Restore'}
											</button>
										{/if}
										<button onclick={() => void forkFromVersion(version.id)}
											class="border border-[#E2E0DB] px-2 py-1 text-xs font-medium text-[#7A7770] hover:bg-[#F7F6F3]">
											Fork
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>

			{:else if !hasOpenRouter}
				<div class="flex flex-1 flex-col items-center justify-center p-6 text-center">
					<svg class="mb-3 h-8 w-8 text-[#7A7770]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
					</svg>
					<p class="mb-2 text-sm text-[#7A7770]">OpenRouter API key required for chat</p>
					<a href="/settings" class="text-sm font-medium text-[#D01012] hover:text-[#B00E10]">Configure in Settings</a>
				</div>
			{:else}
				<!-- Chat messages -->
				<div bind:this={chatContainer} class="flex-1 overflow-y-auto p-4">
					{#if aiMessages.length === 0}
						<div class="flex h-full flex-col items-center justify-center text-center">
							<svg class="mb-3 h-8 w-8 text-[#7A7770]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
							</svg>
							<p class="mb-1 text-sm font-medium text-[#1A1A1A]">Describe what you want to sort</p>
								<p class="text-xs text-[#7A7770]">Use chat to create categories, add rules, and refine your sorting logic.</p>
						</div>
					{:else}
						<div class="space-y-4 min-w-0">
								{#each aiMessages as msg (msg.id)}
									<div class="{msg.role === 'user' ? 'ml-8' : 'mr-8'} min-w-0">
										{#if msg.role === 'assistant'}
										<!-- Tool trace -->
										{#if msg.tool_trace?.length}
												<div class="mb-3 space-y-2">
													{#each msg.tool_trace as trace, traceIndex}
														{@const resultView = getExpandableToolResult(trace.tool, trace.output)}
														{@const resultKey = `${msg.id}-trace-${traceIndex}`}
												<div class="min-w-0 overflow-hidden border border-[#00852B]/15 bg-[#00852B]/5 px-3 py-2.5 text-xs">
													<div class="flex items-start gap-2">
														<div class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-[#00852B]">
																	<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
																	<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
																</svg>
															</div>
														<div class="min-w-0">
															<div class="flex items-center justify-between gap-2">
																<div class="font-medium text-[#00852B]">
																	{toolTraceTitle(trace)}
																</div>
																{#if formatDuration(trace.duration_ms ?? null)}
																	<div class="shrink-0 text-[11px] font-medium text-[#00852B]/60">
																		{formatDuration(trace.duration_ms ?? null)}
																	</div>
																{/if}
															</div>
																{#if resultView}
																	<div class="mt-1 text-[#00852B]/70">
																		<div class="text-[11px] font-medium uppercase tracking-[0.08em] text-[#00852B]/60">
																			{getToolResultSummaryLine(resultView)}
																		</div>
																		{#if resultView.items.length > 0}
																			{#if resultView.layout === 'media-grid'}
																				<div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
																					{#each visibleToolResultItems(resultView, resultKey) as item (item.id)}
																						<div class="overflow-hidden border border-[#00852B]/15 bg-white/80">
																							<div class="relative aspect-[4/3] border-b border-[#00852B]/10 bg-[#00852B]/5">
																								{#if item.imageUrl}
																									<img src={item.imageUrl} alt={item.primary} class="h-full w-full object-contain p-2" loading="lazy" />
																								{:else}
																									<div class="flex h-full items-center justify-center text-[11px] font-medium uppercase tracking-[0.12em] text-[#00852B]/40">
																										No image
																									</div>
																								{/if}
																							</div>
																							<div class="px-2.5 py-2">
																								<div class="line-clamp-2 font-medium text-[#00852B]">{item.primary}</div>
																								{#if item.secondary}
																									<div class="mt-1 line-clamp-2 text-[#00852B]/60">{item.secondary}</div>
																								{/if}
																							</div>
																						</div>
																					{/each}
																				</div>
																			{:else}
																				<div class="mt-2 space-y-1.5">
																					{#each visibleToolResultItems(resultView, resultKey) as item (item.id)}
																						<div class="flex items-start gap-2 border border-[#00852B]/15 bg-white/70 px-2 py-1.5">
																							<div class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[#2F6B42]"></div>
																							<div class="min-w-0">
																								<div class="truncate font-medium text-[#00852B]">{item.primary}</div>
																								{#if item.secondary}
																									<div class="truncate text-[#00852B]/60">{item.secondary}</div>
																								{/if}
																							</div>
																						</div>
																					{/each}
																				</div>
																			{/if}
																			{#if canExpandToolResult(resultView)}
																				<button
																					onclick={() => toggleToolResult(resultKey)}
																				class="mt-2 text-[11px] font-medium text-[#00852B] hover:underline"
																			>
																				{#if isToolResultExpanded(resultKey)}
																					Show less
																				{:else}
																					Show all {resultView.availableCount} {resultView.availableCount === 1 ? resultView.singularLabel : resultView.pluralLabel}
																				{/if}
																			</button>
																		{/if}
																	{/if}
																</div>
															{:else}
																<div class="markdown-body markdown-compact mt-0.5 text-[#00852B]/70">
																	{@html renderMarkdown(trace.output_summary)}
																</div>
															{/if}
														</div>
													</div>
												</div>
												{/each}
											</div>
										{/if}
											<!-- Chat message content -->
										<div class="chat-message-assistant min-w-0 overflow-hidden p-3 text-sm">
											<div class="markdown-body overflow-x-auto">
												{@html renderMarkdown(displayAiMessageContent(msg.content))}
											</div>
											{#if aiMessagePerformanceLabel(msg)}
												<div class="mt-2 text-[11px] text-[#7A7770]">
													{aiMessagePerformanceLabel(msg)}
												</div>
											{/if}
											<!-- Proposal action summaries -->
											{#if msg.applied_at && msg.proposal}
												{@const actions = proposalActionSummaries(msg.proposal)}
												{#if actions.length}
													<div class="mt-2 space-y-0.5 border-t border-[#E2E0DB] pt-2">
														{#each actions as action}
															<div class="flex items-center gap-1.5 text-xs text-[#00852B]">
																<svg class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor">
																	<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
																</svg>
																{action}
															</div>
														{/each}
													</div>
												{/if}
											{/if}
										</div>
									{:else}
										<!-- User message -->
										<div class="chat-message-user min-w-0 overflow-hidden p-3 text-sm">
											<div class="whitespace-pre-wrap">{msg.content}</div>
										</div>
									{/if}
								</div>
							{/each}
								{#if aiBusy}
									<div class="mr-8">
										<div class="mb-2 space-y-2" aria-live="polite">
											{#each visibleAiProgressCards as card (card.id)}
												{@const resultView = getExpandableToolResult(card.tool, card.output)}
												<div
													class="px-3 py-2.5 text-xs {card.status === 'active'
														? 'border border-[#E7D7AA] bg-[#FFF9E8]'
														: 'border border-[#CDE5D5] bg-[#F2FAF5]'}"
												>
													<div class="flex items-start gap-2">
														<div class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center {card.status === 'active' ? 'text-[#8A6D1F]' : 'text-[#00852B]'}">
															{#if card.status === 'active'}
															<svg class="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
																<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
																<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
															</svg>
														{:else}
															<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
																<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
															</svg>
														{/if}
													</div>
														<div class="min-w-0 flex-1">
															<div class="flex items-center justify-between gap-2">
																<div class="font-medium {card.status === 'active' ? 'text-[#6B571C]' : 'text-[#00852B]'}">
																	{card.title}
																</div>
																{#if formatDuration(card.durationMs ?? null)}
																	<div class="shrink-0 text-[11px] font-medium {card.status === 'active' ? 'text-[#8A6D1F]/70' : 'text-[#00852B]/60'}">
																		{formatDuration(card.durationMs ?? null)}
																	</div>
																{/if}
															</div>
																{#if resultView}
																	<div class="mt-1 {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-[#00852B]/70'}">
																		<div class="text-[11px] font-medium uppercase tracking-[0.08em] {card.status === 'active' ? 'text-[#8A6D1F]' : 'text-[#00852B]/60'}">
																			{getToolResultSummaryLine(resultView)}
																		</div>
																		{#if resultView.items.length > 0}
																			{#if resultView.layout === 'media-grid'}
																				<div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
																					{#each visibleToolResultItems(resultView, card.id) as item (item.id)}
																						<div class="overflow-hidden border {card.status === 'active' ? 'border-[#E7D7AA] bg-white/70' : 'border-[#00852B]/15 bg-white/80'}">
																							<div class="relative aspect-[4/3] border-b {card.status === 'active' ? 'border-[#F0E2BD] bg-[#FFFDF5]' : 'border-[#00852B]/10 bg-[#00852B]/5'}">
																								{#if item.imageUrl}
																									<img src={item.imageUrl} alt={item.primary} class="h-full w-full object-contain p-2" loading="lazy" />
																								{:else}
																									<div class="flex h-full items-center justify-center text-[11px] font-medium uppercase tracking-[0.12em] {card.status === 'active' ? 'text-[#CCBC8C]' : 'text-[#00852B]/40'}">
																										No image
																									</div>
																								{/if}
																							</div>
																							<div class="px-2.5 py-2">
																								<div class="line-clamp-2 font-medium {card.status === 'active' ? 'text-[#6B571C]' : 'text-[#00852B]'}">{item.primary}</div>
																								{#if item.secondary}
																									<div class="mt-1 line-clamp-2 {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-[#00852B]/60'}">{item.secondary}</div>
																								{/if}
																							</div>
																						</div>
																					{/each}
																				</div>
																			{:else}
																				<div class="mt-2 space-y-1.5">
																					{#each visibleToolResultItems(resultView, card.id) as item (item.id)}
																						<div class="flex items-start gap-2 border px-2 py-1.5 {card.status === 'active' ? 'border-[#E7D7AA] bg-white/60' : 'border-[#00852B]/15 bg-white/70'}">
																							<div class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full {card.status === 'active' ? 'bg-[#8A6D1F]' : 'bg-[#2F6B42]'}"></div>
																							<div class="min-w-0">
																								<div class="truncate font-medium {card.status === 'active' ? 'text-[#6B571C]' : 'text-[#00852B]'}">{item.primary}</div>
																								{#if item.secondary}
																									<div class="truncate {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-[#00852B]/60'}">{item.secondary}</div>
																								{/if}
																							</div>
																						</div>
																					{/each}
																				</div>
																			{/if}
																			{#if canExpandToolResult(resultView)}
																				<button
																					onclick={() => toggleToolResult(card.id)}
																				class="mt-2 text-[11px] font-medium {card.status === 'active' ? 'text-[#8A6D1F]' : 'text-[#00852B]'} hover:underline"
																			>
																				{#if isToolResultExpanded(card.id)}
																					Show less
																				{:else}
																					Show all {resultView.availableCount} {resultView.availableCount === 1 ? resultView.singularLabel : resultView.pluralLabel}
																				{/if}
																			</button>
																		{/if}
																	{/if}
																</div>
															{:else if card.detail}
																<div class="markdown-body markdown-compact mt-0.5 {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-[#00852B]/70'}">
																	{@html renderMarkdown(card.detail)}
																</div>
														{/if}
													</div>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					{/if}
				</div>

				<!-- Chat input -->
				<div class="border-t border-[#E2E0DB] p-3">
					<div class="flex gap-2">
						<input type="text" bind:value={aiMessage}
							placeholder={isNewProfile && workingRules.length === 0
								? 'e.g. Sort Technic parts by function: gears, beams, connectors...'
									: 'Describe a change...'}
							class="min-w-0 flex-1 border border-[#E2E0DB] px-3 py-2 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
							onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void sendAiMessage(); } }}
							disabled={aiBusy} />
						<button onclick={() => void sendAiMessage()} disabled={aiBusy || !aiMessage.trim()}
							class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50">
							{aiBusy ? '...' : 'Send'}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	<!-- Sticky bottom bar -->
	{#if hasUnsavedChanges}
		<div class="fixed bottom-0 left-0 right-0 z-30 border-t border-[#E2E0DB] bg-white px-4 py-3">
			<div class="mx-auto flex max-w-7xl items-center justify-between">
				<div class="flex items-center gap-2 text-sm text-[#7A7770]">
					<span class="inline-block h-2 w-2 bg-[#FFD500]"></span>
					Unsaved changes
				</div>
				<button onclick={openSavePopover} disabled={savingVersion}
					class="bg-[#D01012] px-4 py-2 text-sm font-medium text-white hover:bg-[#B00E10] disabled:opacity-50">
					Save
				</button>
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

<!-- Accordion Node Snippet -->
{#snippet accordionNode(inputRule: SortingProfileRule, depth: number)}
	{@const rule = liveRuleForRender(inputRule)}
	{@const isOpen = expandedNodes.has(rule.id)}
	{@const hasChildren = rule.children.length > 0}
	{@const partCount = getPartCount(rule.id)}

	<div class="{depth > 0 ? 'ml-4 border-l border-[#E2E0DB]' : ''}">
		<!-- Collapsed header -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div onclick={() => { toggleNode(rule.id); selectRule(rule.id); }}
			onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { toggleNode(rule.id); selectRule(rule.id); } }}
			role="button" tabindex="0"
			class="group flex w-full cursor-pointer items-center gap-2 border-b border-[#E2E0DB] px-3 py-2 text-left transition-colors hover:bg-[#F7F6F3]
				{isOpen ? 'bg-[#D01012]/8' : ''}">
			<!-- Chevron / Set image -->
			{#if rule.rule_type === 'set' && rule.set_meta?.img_url}
				<img src={rule.set_meta.img_url} alt={rule.name} class="h-16 w-16 shrink-0 object-contain" />
			{:else}
				<svg class="h-3.5 w-3.5 shrink-0 text-[#7A7770] transition-transform {isOpen ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
				</svg>
			{/if}
			<!-- Name + summary -->
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-2">
					<span class="truncate text-sm font-medium {rule.disabled ? 'text-[#7A7770] line-through' : 'text-[#1A1A1A]'}">{rule.name}</span>
					{#if rule.disabled}
						<span class="shrink-0 text-[10px] uppercase tracking-wide text-[#7A7770]">off</span>
					{/if}
				</div>
				{#if !isOpen}
					<div class="mt-0.5 truncate text-xs text-[#7A7770]">
						{conditionSummary(rule)}
					</div>
				{/if}
			</div>
			<!-- Header actions -->
			<div class="flex shrink-0 items-center gap-2">
				{#if !isPreview}
					<!-- Hover-only actions (left of permanent items) -->
					<button onclick={(e) => { e.stopPropagation(); moveRule(rule.id, -1); }}
						class="p-1 text-[#7A7770] hover:text-[#1A1A1A] opacity-0 group-hover:opacity-100 transition-opacity" aria-label="Move up" title="Move up">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button onclick={(e) => { e.stopPropagation(); moveRule(rule.id, 1); }}
						class="p-1 text-[#7A7770] hover:text-[#1A1A1A] opacity-0 group-hover:opacity-100 transition-opacity" aria-label="Move down" title="Move down">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button onclick={(e) => { e.stopPropagation(); deleteRule(rule.id); }}
						class="p-1 text-[#D01012] opacity-0 group-hover:opacity-100 transition-opacity hover:text-[#B00E10]" aria-label="Delete rule" title="Delete">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
						</svg>
					</button>
				{/if}
				<!-- Permanent items (always visible, right edge) -->
				{#if hasChildren}
					<span class="text-xs text-[#7A7770]">{rule.children.length} sub</span>
				{/if}
				{#if !isPreview}
					<!-- Toggle switch -->
					<button onclick={(e) => { e.stopPropagation(); updateRule(rule.id, { disabled: !rule.disabled }); }}
						class="relative inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full transition-colors {rule.disabled ? 'bg-gray-300' : 'bg-[#00852B]'}"
						title={rule.disabled ? 'Enable rule' : 'Disable rule'}
						role="switch"
						aria-checked={!rule.disabled}>
						<span class="inline-block h-3 w-3 rounded-full bg-white shadow transition-transform {rule.disabled ? 'translate-x-0.5' : 'translate-x-3.5'}"></span>
					</button>
				{/if}
			</div>
		</div>

		<!-- Expanded editor -->
		{#if isOpen}
			{#if rule.rule_type === 'set'}
				<!-- Set rule editor -->
				<div class="border-b border-[#E2E0DB] bg-white px-3 py-3">
					{#if isCustomSetRule(rule)}
						<div class="mb-3">
							<input
								type="text"
								value={rule.name}
								oninput={(e) => updateCustomSetName(rule.id, (e.currentTarget as HTMLInputElement).value)}
								class="mb-1 w-full border border-[#E2E0DB] px-2 py-1 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]"
							/>
							<div class="text-xs text-[#7A7770]">
								Custom set · {customSetPartsLabel(rule)}
							</div>
						</div>
						{#if catalogColorsLoading}
							<div class="mb-3 text-xs text-[#7A7770]">Loading colors...</div>
						{/if}
						<!-- Action buttons above parts -->
						<div class="mb-3 flex items-center gap-2">
							<button onclick={() => openBrickLinkCsvImport(rule.id)}
								disabled={importingCsvForRule === rule.id}
								class="border border-[#E2E0DB] bg-white px-3 py-1.5 text-xs font-medium text-[#7A7770] hover:bg-[#F7F6F3] hover:text-[#1A1A1A] disabled:opacity-50">
								{importingCsvForRule === rule.id ? 'Importing...' : 'Import CSV'}
							</button>
							<button onclick={() => {
								void ensureCatalogColorsLoaded();
								addingPartForRule = addingPartForRule === rule.id ? null : rule.id;
							}}
								class="border border-[#E2E0DB] bg-white px-3 py-1.5 text-xs font-medium text-[#7A7770] hover:bg-[#F7F6F3] hover:text-[#1A1A1A]">
								Add Part
							</button>
						</div>
						{#if customSetImportStatus[rule.id]}
							<div class="mb-3 border px-3 py-2 text-xs {customSetImportStatus[rule.id].tone === 'error'
								? 'border-[#F4C7C7] bg-[#D01012]/8 text-[#9B1D20]'
								: 'border-[#CDE5D5] bg-[#F2FAF5] text-[#2F6B42]'}">
								{customSetImportStatus[rule.id].text}
							</div>
						{/if}
						<div class="space-y-2">
							{#if (rule.custom_parts?.length ?? 0) === 0}
								<div class="border border-dashed border-[#E2E0DB] px-3 py-4 text-center text-xs text-[#7A7770]">
									No parts yet. Add the items you want this custom set to collect.
								</div>
							{:else}
								{#each rule.custom_parts ?? [] as part, index (`${part.part_num}-${index}`)}
									{@const normalizedPartColorId = normalizeCustomColorId(part.color_id)}
									{@const partColorLabel = part.color_name ?? colorLabel(normalizedPartColorId)}
									{@const availableColorOptions = customPartColorOptions(part)}
									<div class="flex items-start gap-3 border border-[#E2E0DB] p-2">
										{#if part.img_url}
											<img src={part.img_url} alt={part.part_name ?? part.part_num} class="h-14 w-14 shrink-0 object-contain" />
										{:else}
											<div class="flex h-14 w-14 shrink-0 items-center justify-center bg-[#F7F6F3] text-[10px] uppercase tracking-wide text-[#7A7770]">Part</div>
										{/if}
										<div class="min-w-0 flex-1">
											<div class="truncate text-sm font-medium text-[#1A1A1A]">
												{part.part_name ?? part.part_num}
											</div>
											<div class="truncate text-xs text-[#7A7770]">
												{part.part_num}
												{#if partColorLabel}
													· {partColorLabel}
												{/if}
												{#if part.part_source === 'bricklink'}
													· BrickLink import
												{/if}
											</div>
											<div class="mt-2 grid gap-2 md:grid-cols-[minmax(0,1fr)_96px_80px_auto]">
												<select
													onchange={(e) => {
														const nextColorId = Number((e.currentTarget as HTMLSelectElement).value);
														updateCustomSetPart(rule.id, index, {
															color_id: nextColorId,
															color_name: customPartColorLabel(part, nextColorId)
														});
													}}
													class="min-w-0 border border-[#E2E0DB] px-2 py-1 text-xs focus:border-[#D01012] focus:outline-none"
												>
													{#each availableColorOptions as option (`${part.part_num}-${option.value}`)}
														<option value={option.value} selected={option.value === normalizedPartColorId}>{option.label}</option>
													{/each}
												</select>
												<input
													type="number"
													min="1"
													value={String(part.quantity)}
													oninput={(e) => updateCustomSetPart(rule.id, index, {
														quantity: Math.max(1, Number((e.currentTarget as HTMLInputElement).value) || 1)
													})}
													class="border border-[#E2E0DB] px-2 py-1 text-xs focus:border-[#D01012] focus:outline-none"
												/>
												<div class="flex items-center text-xs text-[#7A7770]">
													{part.quantity === 1 ? '1 part' : `${part.quantity} parts`}
												</div>
												<button
													onclick={() => removeCustomSetPart(rule.id, index)}
													class="px-2 py-1 text-xs text-[#D01012] hover:text-[#B00E10]"
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
									onSelect={(part) => addCustomSetPart(rule.id, part)}
									onCancel={() => {
										addingPartForRule = null;
									}}
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
									oninput={(e) => updateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
									class="mb-1 w-full border border-[#E2E0DB] px-2 py-1 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
								<div class="mb-2 text-xs text-[#7A7770]">
									{rule.set_num} · {rule.set_meta?.year ?? '?'} · {rule.set_meta?.num_parts ?? '?'} parts
								</div>
								{#if rule.set_num}
									<a href={`https://rebrickable.com/sets/${rule.set_num}/`}
										target="_blank" rel="noopener noreferrer"
										class="inline-flex items-center gap-1 text-xs text-[#D01012] hover:underline">
										View on Rebrickable
										<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
											<path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.25-.75a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V6.31l-5.97 5.97a.75.75 0 01-1.06-1.06l5.97-5.97H12.25a.75.75 0 01-.75-.75z" clip-rule="evenodd" />
										</svg>
									</a>
								{/if}
							</div>
						</div>
						<div class="mb-3 flex items-center gap-4">
							<label class="flex items-center gap-2 text-xs text-[#7A7770]">
								<button onclick={() => updateRule(rule.id, { include_spares: !(rule.include_spares ?? false) } as any)}
									class="relative inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full transition-colors {rule.include_spares ? 'bg-[#00852B]' : 'bg-gray-300'}"
									role="switch"
									aria-checked={rule.include_spares ?? false}
									type="button">
									<span class="inline-block h-3 w-3 rounded-full bg-white shadow transition-transform {rule.include_spares ? 'translate-x-3.5' : 'translate-x-0.5'}"></span>
								</button>
								Include spare parts
							</label>
						</div>
						<!-- Change set inline search -->
						{#if changingSetForRule === rule.id}
							<div class="mb-3">
								<SetSearch onSelect={(set) => {
									updateRule(rule.id, {
										set_source: 'rebrickable',
										set_num: set.set_num,
										name: set.name,
										custom_parts: [],
										set_meta: { name: set.name, year: set.year, num_parts: set.num_parts, img_url: set.img_url },
									} as any);
									changingSetForRule = null;
								}} onCancel={() => { changingSetForRule = null; }} />
							</div>
						{/if}
					{/if}
					{#if !isCustomSetRule(rule)}
						<!-- Change set action for rebrickable sets -->
						<div class="flex items-center gap-2 border-t border-[#E2E0DB] pt-2">
							<button onclick={() => { changingSetForRule = changingSetForRule === rule.id ? null : rule.id; }}
								class="text-xs text-[#D01012] hover:text-[#B00E10]">
								Change Set
							</button>
						</div>
					{/if}
				</div>
			{:else}
				<!-- Filter rule editor -->
				<div class="border-b border-[#E2E0DB] bg-white px-3 py-3">
					<!-- Name + match mode row -->
					<div class="mb-3 flex items-center gap-2">
						<input type="text" value={rule.name}
							oninput={(e) => updateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
							class="min-w-0 flex-1 border border-[#E2E0DB] px-2 py-1 text-sm focus:border-[#D01012] focus:outline-none focus:ring-1 focus:ring-[#D01012]" />
						<select value={rule.match_mode}
							onchange={(e) => updateRule(rule.id, { match_mode: (e.currentTarget as HTMLSelectElement).value })}
							class="border border-[#E2E0DB] px-2 py-1 text-xs text-[#7A7770] focus:border-[#D01012] focus:outline-none">
							<option value="all">Match ALL</option>
							<option value="any">Match ANY</option>
						</select>
					</div>

					<!-- Conditions -->
					{#if rule.conditions.length > 0}
						<div class="mb-2 space-y-1.5">
							{#each rule.conditions as cond (cond.id)}
								<div class="flex items-center gap-1.5">
									<select value={cond.field}
										onchange={(e) => {
											const field = (e.currentTarget as HTMLSelectElement).value;
											const ops = opOptionsByField[field] ?? ['eq'];
											updateCondition(rule.id, cond.id, { field, op: ops[0] });
										}}
										class="w-36 border border-[#E2E0DB] px-1.5 py-1 text-xs focus:border-[#D01012] focus:outline-none">
										{#each fieldOptions as f}
											<option value={f}>{f}</option>
										{/each}
									</select>
									<select value={cond.op}
										onchange={(e) => updateCondition(rule.id, cond.id, { op: (e.currentTarget as HTMLSelectElement).value })}
										class="w-20 border border-[#E2E0DB] px-1.5 py-1 text-xs focus:border-[#D01012] focus:outline-none">
										{#each opOptionsByField[cond.field] ?? ['eq'] as op}
											<option value={op}>{opLabels[op] ?? op}</option>
										{/each}
									</select>
									<input type="text" value={formatConditionValue(cond.value)}
										oninput={(e) => updateCondition(rule.id, cond.id, { value: parseConditionValue((e.currentTarget as HTMLInputElement).value) })}
										class="min-w-0 flex-1 border border-[#E2E0DB] px-1.5 py-1 text-xs focus:border-[#D01012] focus:outline-none"
										placeholder="value" />
									<button onclick={() => deleteCondition(rule.id, cond.id)}
										class="shrink-0 p-1 text-[#7A7770] hover:text-[#D01012]" aria-label="Remove condition">
										<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
											<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
										</svg>
									</button>
								</div>
							{/each}
						</div>
					{/if}
					<button onclick={() => addCondition(rule.id)}
						class="mb-3 text-xs font-medium text-[#D01012] hover:text-[#B00E10]">+ Add condition</button>

					<!-- Children (recursive) -->
					{#if hasChildren}
						<div class="mb-2">
							{#each rule.children as child (child.id)}
								{@render accordionNode(child, depth + 1)}
							{/each}
						</div>
					{/if}

					<!-- Actions row -->
					<div class="flex items-center gap-2 border-t border-[#E2E0DB] pt-2">
						<button onclick={() => addRule(rule.id)}
							class="text-xs font-medium text-[#D01012] hover:text-[#B00E10]">+ Add child</button>
					</div>

					<!-- Preview -->
					{#if selectedRuleId === rule.id && rulePreview}
						<div class="mt-2 border-t border-[#E2E0DB] pt-2">
							<div class="mb-1 flex items-center justify-between text-xs text-[#7A7770]">
								<span>{rulePreview.total} matching parts</span>
								{#if rulePreviewLoading}
									<span class="text-[#7A7770]">Loading...</span>
								{/if}
							</div>
							{#if rulePreview.sample.length > 0}
								<div class="space-y-0.5">
									{#each rulePreview.sample as part}
										<div class="truncate text-xs text-[#7A7770]">{part.part_num} — {part.name}</div>
									{/each}
								</div>
								{#if !rulePreviewExpanded && rulePreview.total > 5}
									<button onclick={loadMorePreview} class="mt-1 text-xs text-[#D01012] hover:text-[#B00E10]">
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
{/snippet}
