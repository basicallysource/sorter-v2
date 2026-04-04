<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type AiToolTraceItem,
		type SortingProfileAiMessage,
		type SortingProfileDetail,
		type SortingProfileFallbackMode,
		type SortingProfileRule
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

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

	let savingVersion = $state(false);
	let showSavePopover = $state(false);
	let changeNote = $state('');

	let rulePreview = $state<RulePreviewResult | null>(null);
	let rulePreviewLoading = $state(false);
	let rulePreviewExpanded = $state(false);
	let previewDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	// AI state
	let aiMessages = $state<SortingProfileAiMessage[]>([]);
	let aiMessage = $state('');
	let aiBusy = $state(false);
	let aiProgress = $state<Array<{ type: string; tool?: string; input?: Record<string, unknown>; output_summary?: string }>>([]);

	const profileId = $derived(page.params.id ?? '');
	const isNewProfile = $derived(page.url.searchParams.get('new') === '1');
	const binCount = $derived(page.url.searchParams.get('bins'));

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
		workingRules = structuredClone(cv.rules);
		workingFallbackMode = structuredClone(cv.fallback_mode);
		workingDefaultCategoryId = cv.default_category_id ?? '';
		originalRulesJson = JSON.stringify(cv.rules);
		originalFallbackJson = JSON.stringify(cv.fallback_mode);
		originalDefaultCategoryId = cv.default_category_id ?? '';
		selectedRuleId = cv.rules[0]?.id ?? null;
		expandedNodes = new Set();
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
		const nextRules = $state.snapshot(workingRules) as SortingProfileRule[];
		mutator(nextRules);
		workingRules = nextRules;
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
			const newRule = makeRule(`Category ${workingRules.length + 1}`);
			withRules((rules) => rules.push(newRule));
			selectedRuleId = newRule.id;
			expandedNodes = new Set([...expandedNodes, newRule.id]);
		}
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
		rulePreviewLoading = true;
		try {
			rulePreview = (await api.previewSortingRule(profileDocument(), { rule_id: ruleId, limit: 5 })) as RulePreviewResult;
		} catch { rulePreview = null; }
		finally { rulePreviewLoading = false; }
	}

	async function loadMorePreview() {
		if (!selectedRuleId) return;
		rulePreviewLoading = true;
		try {
			rulePreview = (await api.previewSortingRule(profileDocument(), { rule_id: selectedRuleId, limit: 25 })) as RulePreviewResult;
			rulePreviewExpanded = true;
		} catch { /* keep existing */ }
		finally { rulePreviewLoading = false; }
	}

	// --- Save ---
	function openSavePopover() { changeNote = ''; showSavePopover = true; }
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

	// --- AI ---
	async function sendAiMessage() {
		if (!profile || !aiMessage.trim()) return;
		aiBusy = true;
		aiProgress = [];
		error = null;
		const userMsg = aiMessage.trim();
		aiMessage = '';
		try {
			let response: import('$lib/api').SortingProfileAiMessage;
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
				aiProgress = [];
				response = await api.createSortingProfileAiMessage(profile.id, {
					message: userMsg,
					version_id: profile.current_version?.id ?? null,
					selected_rule_id: selectedRuleId
				});
			}
			aiMessages = [...aiMessages, response];

			// Auto-apply if the AI returned a proposal
			if (response.proposal) {
				const version = await api.applySortingProfileAiMessage(profile.id, response.id, {});
				const idx = aiMessages.findIndex((m) => m.id === response.id);
				if (idx >= 0) {
					aiMessages[idx] = { ...aiMessages[idx], applied_at: new Date().toISOString() };
				}
				lastLoadedProfileId = '';
				await loadProfile();
			}
		} catch (e: any) {
			error = e.error || e.message || 'AI request failed';
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

	function toolTraceLabel(item: AiToolTraceItem): string {
		if (item.tool === 'search_parts') {
			const q = (item.input as Record<string, unknown>).query ?? '';
			return `Searched parts for "${q}"`;
		}
		return item.tool;
	}

	function proposalActionSummaries(proposal: Record<string, unknown> | null): string[] {
		if (!proposal) return [];
		const proposals = proposal.proposals;
		if (!Array.isArray(proposals)) return [];
		return proposals.map((p: Record<string, unknown>) => {
			const action = p.action as string;
			const name = (p.name as string) || 'rule';
			if (action === 'create') return `Created "${name}"`;
			if (action === 'edit') return `Edited "${name}"`;
			if (action === 'move') return `Moved "${name}"`;
			if (action === 'delete') return `Deleted "${name}"`;
			return `${action} "${name}"`;
		});
	}
</script>

<svelte:head>
	<title>{profile ? `Edit ${profile.name} - SortHive` : 'Edit Profile - SortHive'}</title>
</svelte:head>

{#if loading}
	<Spinner />
{:else if !profile}
	<div class="border border-red-200 bg-red-50 p-4 text-sm text-red-700">Profile not found.</div>
{:else if !profile.current_version}
	<div class="border border-red-200 bg-red-50 p-4 text-sm text-red-700">No version available.</div>
{:else}
	<!-- Header -->
	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href="/profiles/{profile.id}" class="text-gray-400 hover:text-gray-600" title="Back to profile">
				<svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
				</svg>
			</a>
			<div>
				<h1 class="text-xl font-bold text-gray-900">{profile.name}</h1>
				<span class="text-xs text-gray-500">v{profile.current_version.version_number}</span>
			</div>
		</div>
		<div class="relative">
			<button onclick={openSavePopover} disabled={savingVersion}
				class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
				Save
			</button>
			{#if showSavePopover}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="fixed inset-0 z-40" onclick={closeSavePopover} onkeydown={(e) => { if (e.key === 'Escape') closeSavePopover(); }}></div>
				<div class="absolute right-0 top-full z-50 mt-2 w-72 border border-gray-200 bg-white p-4 shadow-lg">
					<h3 class="mb-2 text-sm font-semibold text-gray-900">Save New Version</h3>
					<label class="mb-1 block text-xs text-gray-500" for="save-note">What changed? (optional)</label>
					<input id="save-note" type="text" bind:value={changeNote} placeholder="e.g. Added gear categories"
						class="mb-3 w-full border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
						onkeydown={(e) => { if (e.key === 'Enter') void saveVersion(); }} />
					<div class="flex justify-end gap-2">
						<button onclick={closeSavePopover} class="border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
						<button onclick={() => void saveVersion()} disabled={savingVersion}
							class="bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50">
							{savingVersion ? 'Saving...' : 'Save'}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if error}
		<div class="mb-3 border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{/if}
	{#if success}
		<div class="mb-3 flex items-center justify-between border border-green-200 bg-green-50 p-3 text-sm text-green-700">
			<span>{success}</span>
			<button onclick={dismissSuccess} class="text-green-600 hover:text-green-800" aria-label="Dismiss">
				<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
				</svg>
			</button>
		</div>
	{/if}

	<!-- Main 2-column layout: Rules (left, wider) | AI Chat (right) -->
	<div class="grid min-h-0 grid-cols-1 gap-4 overflow-hidden xl:grid-cols-[3fr_2fr]" style="height: calc(100vh - 200px);">

		<!-- LEFT: Rules (accordion) -->
		<div class="flex min-h-0 flex-col border border-gray-200 bg-white">
			<div class="border-b border-gray-200 px-4 py-2">
				<h2 class="text-sm font-semibold text-gray-900">Rules</h2>
			</div>
			<div class="flex-1 overflow-y-auto">
				{#if workingRules.length === 0}
					<div class="p-4 text-center text-sm text-gray-400">
						No rules yet. Use the AI chat to generate categories, or add one manually.
					</div>
				{:else}
					{#each workingRules as rule (rule.id)}
						{@render accordionNode(rule, 0)}
					{/each}
				{/if}
			</div>
			<div class="border-t border-gray-200 px-3 py-2">
				<button onclick={() => addRule()}
					class="w-full border border-dashed border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-500 hover:border-gray-400 hover:text-gray-700">
					+ Add Category
				</button>
			</div>
			<!-- Fallback -->
			<div class="border-t border-gray-200 px-3 py-2">
				<div class="flex flex-wrap items-center gap-4 text-xs text-gray-600">
					<span class="font-medium text-gray-500">Fallback:</span>
					<label class="flex items-center gap-1">
						<input type="checkbox" checked={workingFallbackMode.rebrickable_categories}
							onchange={(e) => updateFallbackMode('rebrickable_categories', (e.currentTarget as HTMLInputElement).checked)} />
						Rebrickable
					</label>
					<label class="flex items-center gap-1">
						<input type="checkbox" checked={workingFallbackMode.bricklink_categories}
							onchange={(e) => updateFallbackMode('bricklink_categories', (e.currentTarget as HTMLInputElement).checked)} />
						BrickLink
					</label>
					<label class="flex items-center gap-1">
						<input type="checkbox" checked={workingFallbackMode.by_color}
							onchange={(e) => updateFallbackMode('by_color', (e.currentTarget as HTMLInputElement).checked)} />
						By color
					</label>
				</div>
			</div>
		</div>

		<!-- RIGHT: AI Chat -->
		<div class="flex min-h-0 flex-col border border-gray-200 bg-white">
			<div class="border-b border-gray-200 px-4 py-2">
				<div class="flex items-center justify-between">
					<h2 class="text-sm font-semibold text-gray-900">AI Assistant</h2>
					{#if selectedRule}
						<span class="text-xs text-gray-400">Context: {selectedRule.name}</span>
					{/if}
				</div>
			</div>

			{#if !hasOpenRouter}
				<div class="flex flex-1 flex-col items-center justify-center p-6 text-center">
					<svg class="mb-3 h-8 w-8 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
					</svg>
					<p class="mb-2 text-sm text-gray-500">AI Assistant requires an OpenRouter API key</p>
					<a href="/settings" class="text-sm font-medium text-blue-600 hover:text-blue-800">Configure in Settings</a>
				</div>
			{:else}
				<!-- Chat messages -->
				<div bind:this={chatContainer} class="flex-1 overflow-y-auto p-4">
					{#if aiMessages.length === 0}
						<div class="flex h-full flex-col items-center justify-center text-center">
							<svg class="mb-3 h-8 w-8 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
							</svg>
							<p class="mb-1 text-sm font-medium text-gray-700">Describe what you want to sort</p>
							<p class="text-xs text-gray-400">
								{#if isNewProfile && binCount}
									Your profile has {binCount} bins. Tell the AI what kinds of parts you want to sort.
								{:else}
									The AI can create categories, add rules, and refine your sorting logic.
								{/if}
							</p>
						</div>
					{:else}
						<div class="space-y-4">
							{#each aiMessages as msg (msg.id)}
								<div class="{msg.role === 'user' ? 'ml-8' : 'mr-8'}">
									<div class="mb-1 text-xs font-medium {msg.role === 'user' ? 'text-right text-blue-600' : 'text-green-600'}">
										{msg.role === 'user' ? 'You' : 'AI'}
									</div>
									{#if msg.role === 'assistant'}
										<!-- Tool trace -->
										{#if msg.tool_trace?.length}
											<div class="mb-2 space-y-1">
												{#each msg.tool_trace as trace}
													<div class="border border-gray-100 bg-gray-50 px-3 py-2 text-xs">
														<div class="flex items-center gap-1.5 font-medium text-gray-500">
															<svg class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor">
																<path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
															</svg>
															{toolTraceLabel(trace)}
														</div>
														<div class="mt-0.5 text-gray-400">{trace.output_summary}</div>
													</div>
												{/each}
											</div>
										{/if}
										<!-- AI message content -->
										<div class="border border-gray-200 bg-white p-3 text-sm text-gray-600">
											<div class="whitespace-pre-wrap">{msg.content}</div>
											<!-- Proposal action summaries -->
											{#if msg.applied_at && msg.proposal}
												{@const actions = proposalActionSummaries(msg.proposal)}
												{#if actions.length}
													<div class="mt-2 space-y-0.5 border-t border-gray-100 pt-2">
														{#each actions as action}
															<div class="flex items-center gap-1.5 text-xs text-green-600">
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
										<div class="border border-blue-200 bg-blue-50 p-3 text-sm text-gray-700">
											<div class="whitespace-pre-wrap">{msg.content}</div>
										</div>
									{/if}
								</div>
							{/each}
							{#if aiBusy}
								<div class="mr-8">
									<div class="mb-1 text-xs font-medium text-green-600">AI</div>
									<!-- Live progress events -->
									{#if aiProgress.length > 0}
										<div class="mb-2 space-y-1">
											{#each aiProgress as step}
												{#if step.type === 'thinking'}
													<div class="border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-400">
														Analyzing request...
													</div>
												{:else if step.type === 'tool_call'}
													<div class="border border-gray-100 bg-gray-50 px-3 py-2 text-xs">
														<div class="flex items-center gap-1.5 font-medium text-gray-500">
															<svg class="h-3 w-3 shrink-0 animate-spin" viewBox="0 0 24 24" fill="none">
																<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
																<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
															</svg>
															{#if step.tool === 'search_parts'}
																Searching parts for "{step.input?.query}"...
															{:else}
																{step.tool}...
															{/if}
														</div>
													</div>
												{:else if step.type === 'tool_result'}
													<div class="border border-gray-100 bg-gray-50 px-3 py-2 text-xs">
														<div class="flex items-center gap-1.5 font-medium text-gray-500">
															<svg class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor">
																<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
															</svg>
															{#if step.tool === 'search_parts'}
																Searched "{step.input?.query}"
															{:else}
																{step.tool}
															{/if}
														</div>
														{#if step.output_summary}
															<div class="mt-0.5 text-gray-400">{step.output_summary}</div>
														{/if}
													</div>
												{:else if step.type === 'generating'}
													<div class="border border-gray-100 bg-gray-50 px-3 py-2 text-xs">
														<div class="flex items-center gap-1.5 text-gray-400">
															<svg class="h-3 w-3 shrink-0 animate-spin" viewBox="0 0 24 24" fill="none">
																<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
																<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
															</svg>
															Writing rules...
														</div>
													</div>
												{/if}
											{/each}
										</div>
									{:else}
										<div class="border border-gray-200 bg-gray-50 p-3">
											<div class="flex items-center gap-2 text-sm text-gray-400">
												<svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
													<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
													<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
												</svg>
												Thinking...
											</div>
										</div>
									{/if}
								</div>
							{/if}
						</div>
					{/if}
				</div>

				<!-- Chat input -->
				<div class="border-t border-gray-200 p-3">
					<div class="flex gap-2">
						<input type="text" bind:value={aiMessage}
							placeholder={isNewProfile && workingRules.length === 0
								? 'e.g. Sort Technic parts by function: gears, beams, connectors...'
								: 'Ask AI to suggest changes...'}
							class="min-w-0 flex-1 border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
							onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void sendAiMessage(); } }}
							disabled={aiBusy} />
						<button onclick={() => void sendAiMessage()} disabled={aiBusy || !aiMessage.trim()}
							class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
							{aiBusy ? '...' : 'Send'}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	<!-- Sticky bottom bar -->
	{#if hasUnsavedChanges}
		<div class="fixed bottom-0 left-0 right-0 z-30 border-t border-gray-200 bg-white px-4 py-3">
			<div class="mx-auto flex max-w-7xl items-center justify-between">
				<div class="flex items-center gap-2 text-sm text-gray-600">
					<span class="inline-block h-2 w-2 bg-amber-500"></span>
					Unsaved changes
				</div>
				<button onclick={openSavePopover} disabled={savingVersion}
					class="bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
					Save
				</button>
			</div>
		</div>
		<div class="h-16"></div>
	{/if}
{/if}

<!-- Accordion Node Snippet -->
{#snippet accordionNode(rule: SortingProfileRule, depth: number)}
	{@const isOpen = expandedNodes.has(rule.id)}
	{@const hasChildren = rule.children.length > 0}
	{@const partCount = getPartCount(rule.id)}

	<div class="{depth > 0 ? 'ml-4 border-l border-gray-200' : ''}">
		<!-- Collapsed header -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div onclick={() => { toggleNode(rule.id); selectRule(rule.id); }}
			onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { toggleNode(rule.id); selectRule(rule.id); } }}
			role="button" tabindex="0"
			class="group flex w-full cursor-pointer items-center gap-2 border-b border-gray-100 px-3 py-2 text-left transition-colors hover:bg-gray-50
				{isOpen ? 'bg-blue-50' : ''}">
			<!-- Chevron -->
			<svg class="h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform {isOpen ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
			</svg>
			<!-- Name + summary -->
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-2">
					<span class="truncate text-sm font-medium {rule.disabled ? 'text-gray-400 line-through' : 'text-gray-800'}">{rule.name}</span>
					{#if rule.disabled}
						<span class="shrink-0 text-[10px] uppercase tracking-wide text-gray-400">off</span>
					{/if}
				</div>
				{#if !isOpen}
					<div class="mt-0.5 truncate text-xs text-gray-400">
						{conditionSummary(rule)}
					</div>
				{/if}
			</div>
			<!-- Badges -->
			<div class="flex shrink-0 items-center gap-2">
				{#if hasChildren}
					<span class="text-xs text-gray-400">{rule.children.length} sub</span>
				{/if}
				{#if partCount !== null}
					<span class="bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-500">{formatPartCount(partCount)}</span>
				{/if}
			</div>
		</div>

		<!-- Expanded editor -->
		{#if isOpen}
			<div class="border-b border-gray-200 bg-white px-3 py-3">
				<!-- Name + match mode row -->
				<div class="mb-3 flex items-center gap-2">
					<input type="text" value={rule.name}
						oninput={(e) => updateRule(rule.id, { name: (e.currentTarget as HTMLInputElement).value })}
						class="min-w-0 flex-1 border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
					<select value={rule.match_mode}
						onchange={(e) => updateRule(rule.id, { match_mode: (e.currentTarget as HTMLSelectElement).value })}
						class="border border-gray-300 px-2 py-1 text-xs text-gray-600 focus:border-blue-500 focus:outline-none">
						<option value="all">Match ALL</option>
						<option value="any">Match ANY</option>
					</select>
					<label class="flex items-center gap-1 text-xs text-gray-500">
						<input type="checkbox" checked={rule.disabled}
							onchange={(e) => updateRule(rule.id, { disabled: (e.currentTarget as HTMLInputElement).checked })} />
						Disabled
					</label>
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
									class="w-36 border border-gray-300 px-1.5 py-1 text-xs focus:border-blue-500 focus:outline-none">
									{#each fieldOptions as f}
										<option value={f}>{f}</option>
									{/each}
								</select>
								<select value={cond.op}
									onchange={(e) => updateCondition(rule.id, cond.id, { op: (e.currentTarget as HTMLSelectElement).value })}
									class="w-20 border border-gray-300 px-1.5 py-1 text-xs focus:border-blue-500 focus:outline-none">
									{#each opOptionsByField[cond.field] ?? ['eq'] as op}
										<option value={op}>{opLabels[op] ?? op}</option>
									{/each}
								</select>
								<input type="text" value={formatConditionValue(cond.value)}
									oninput={(e) => updateCondition(rule.id, cond.id, { value: parseConditionValue((e.currentTarget as HTMLInputElement).value) })}
									class="min-w-0 flex-1 border border-gray-300 px-1.5 py-1 text-xs focus:border-blue-500 focus:outline-none"
									placeholder="value" />
								<button onclick={() => deleteCondition(rule.id, cond.id)}
									class="shrink-0 p-1 text-gray-400 hover:text-red-500" aria-label="Remove condition">
									<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
										<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
									</svg>
								</button>
							</div>
						{/each}
					</div>
				{/if}
				<button onclick={() => addCondition(rule.id)}
					class="mb-3 text-xs font-medium text-blue-600 hover:text-blue-800">+ Add condition</button>

				<!-- Children (recursive) -->
				{#if hasChildren}
					<div class="mb-2">
						{#each rule.children as child (child.id)}
							{@render accordionNode(child, depth + 1)}
						{/each}
					</div>
				{/if}

				<!-- Actions row -->
				<div class="flex items-center gap-2 border-t border-gray-100 pt-2">
					<button onclick={() => addRule(rule.id)}
						class="text-xs font-medium text-blue-600 hover:text-blue-800">+ Add child</button>
					<div class="flex-1"></div>
					<button onclick={() => moveRule(rule.id, -1)}
						class="p-1 text-gray-400 hover:text-gray-600" aria-label="Move up" title="Move up">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button onclick={() => moveRule(rule.id, 1)}
						class="p-1 text-gray-400 hover:text-gray-600" aria-label="Move down" title="Move down">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button onclick={() => deleteRule(rule.id)}
						class="p-1 text-gray-400 hover:text-red-500" aria-label="Delete rule" title="Delete">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
						</svg>
					</button>
				</div>

				<!-- Preview -->
				{#if selectedRuleId === rule.id && rulePreview}
					<div class="mt-2 border-t border-gray-100 pt-2">
						<div class="mb-1 flex items-center justify-between text-xs text-gray-500">
							<span>{rulePreview.total} matching parts</span>
							{#if rulePreviewLoading}
								<span class="text-gray-400">Loading...</span>
							{/if}
						</div>
						{#if rulePreview.sample.length > 0}
							<div class="space-y-0.5">
								{#each rulePreview.sample as part}
									<div class="truncate text-xs text-gray-500">{part.part_num} — {part.name}</div>
								{/each}
							</div>
							{#if !rulePreviewExpanded && rulePreview.total > 5}
								<button onclick={loadMorePreview} class="mt-1 text-xs text-blue-600 hover:text-blue-800">
									Show more ({rulePreview.total} total)
								</button>
							{/if}
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>
{/snippet}
