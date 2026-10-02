// The profile editor's rules, as plain data and pure functions: making a rule,
// changing one without touching the others, putting them in order, and turning
// the draft into the document the server compiles. Nothing here knows about the
// page, so every edit is a new array or object and the page only swaps them in.

import type {
	NoBinPolicy,
	ProfileDocument,
	ProfileProblem,
	ProfileWarning,
	SortingProfileCondition,
	SortingProfileFallbackMode,
	SortingProfileRule
} from '$lib/api';
import { uuid } from '$lib/uuid';

// Standing in for a rule's ID: the last row, what the rules leave over.
export const REST_ID = 'rest';

export type Rule = SortingProfileRule;
export type Condition = SortingProfileCondition;
export type FallbackChoice = 'none' | 'bl_category' | 'rb_category' | 'color';
// When a piece's category has no bin and none is free: the machine's own
// setting (it stops and asks by default), Everything else, or a shared bin.
export type NoBinChoice = 'machine' | NoBinPolicy;

// --- What happens to the pieces no rule takes ---------------------------------

// One choice, read the way the server reads the three flags it stores.
export function fallbackChoice(mode: SortingProfileFallbackMode | null | undefined): FallbackChoice {
	if (mode?.bricklink_categories) return 'bl_category';
	if (mode?.rebrickable_categories) return 'rb_category';
	if (mode?.by_color) return 'color';
	return 'none';
}

export function noBinChoice(mode: SortingProfileFallbackMode | null | undefined): NoBinChoice {
	return mode?.no_bin === 'misc' || mode?.no_bin === 'share' ? mode.no_bin : 'machine';
}

export function fallbackMode(choice: FallbackChoice, noBin: NoBinChoice = 'machine'): SortingProfileFallbackMode {
	return {
		rebrickable_categories: choice === 'rb_category',
		bricklink_categories: choice === 'bl_category',
		by_color: choice === 'color',
		no_bin: noBin === 'machine' ? null : noBin
	};
}

// --- Making rules ----------------------------------------------------------------

export function newRule(name: string): Rule {
	return {
		id: uuid(),
		rule_type: 'filter',
		name,
		match_mode: 'all',
		conditions: [],
		children: [],
		disabled: false,
		image_url: null
	};
}

export function newKitRule(name: string, kitId: string): Rule {
	return {
		id: uuid(),
		rule_type: 'kit',
		kit_id: kitId,
		name,
		match_mode: 'all',
		conditions: [],
		children: [],
		disabled: false,
		image_url: null
	};
}

// A condition with no field yet. It is a place to choose one; the server never
// sees it (see `documentFor`).
export function newCondition(): Condition {
	return { id: uuid(), field: '', op: '', value: '' };
}

// A group inside a rule: pieces are combined the other way from the rule around
// it, which is what a group is usually for ("red or blue", inside "all of").
export function newGroup(parentMode: string): Rule {
	return { ...newRule('Group'), match_mode: parentMode === 'any' ? 'all' : 'any', conditions: [newCondition()] };
}

// What the server stored, in the one shape the editor works with. `aliases`
// maps a field's older name, still found in saved rules, to the field it is now.
export function normalizeRule(rule: Rule, aliases: Record<string, string> = {}): Rule {
	return {
		...rule,
		rule_type: rule.rule_type ?? 'filter',
		match_mode: rule.match_mode === 'any' ? 'any' : 'all',
		negate: Boolean(rule.negate),
		conditions: (rule.conditions ?? []).map((condition) => ({
			...condition,
			id: condition.id || uuid(),
			field: aliases[condition.field] ?? condition.field
		})),
		children: (rule.children ?? []).map((child) => normalizeRule(child, aliases)),
		disabled: Boolean(rule.disabled)
	};
}

export function isKitRule(rule: Rule): boolean {
	return rule.rule_type === 'kit' || rule.rule_type === 'set';
}

// "Rule 3": a name nobody chose, which a part or a category may rename.
export function hasDefaultName(rule: Rule): boolean {
	return /^Rule \d+$/.test(rule.name.trim());
}

export function nextRuleName(rules: Rule[]): string {
	const taken = new Set(rules.map((rule) => rule.name));
	for (let n = rules.length + 1; ; n += 1) {
		if (!taken.has(`Rule ${n}`)) return `Rule ${n}`;
	}
}

// A copy with new IDs all the way down, so the two can be told apart.
export function duplicateRule(rule: Rule): Rule {
	const copy = (source: Rule): Rule => ({
		...source,
		id: uuid(),
		conditions: source.conditions.map((condition) => ({ ...condition, id: uuid() })),
		children: source.children.map(copy)
	});
	return { ...copy(rule), name: `${rule.name} copy` };
}

// --- Changing the list of rules ---------------------------------------------------

export function replaceRule(rules: Rule[], id: string, next: Rule): Rule[] {
	return rules.map((rule) => (rule.id === id ? next : rule));
}

export function patchRule(rules: Rule[], id: string, patch: Partial<Rule>): Rule[] {
	return rules.map((rule) => (rule.id === id ? { ...rule, ...patch } : rule));
}

export function removeRule(rules: Rule[], id: string): Rule[] {
	return rules.filter((rule) => rule.id !== id);
}

export function moveRule(rules: Rule[], id: string, delta: -1 | 1): Rule[] {
	const from = rules.findIndex((rule) => rule.id === id);
	const to = from + delta;
	if (from < 0 || to < 0 || to >= rules.length) return rules;
	return reorderRule(rules, id, delta > 0 ? to + 1 : to);
}

// Put a rule where a drop at `slot` means: slot 0 is before the first rule, slot
// `rules.length` after the last. Dropping next to itself changes nothing.
export function reorderRule(rules: Rule[], id: string, slot: number): Rule[] {
	const from = rules.findIndex((rule) => rule.id === id);
	if (from < 0) return rules;
	const to = slot > from ? slot - 1 : slot;
	if (to === from) return rules;
	const next = [...rules];
	const [moved] = next.splice(from, 1);
	next.splice(to, 0, moved);
	return next;
}

// --- Inside one rule --------------------------------------------------------------

export function replaceCondition(rule: Rule, id: string, next: Condition): Rule {
	return { ...rule, conditions: rule.conditions.map((c) => (c.id === id ? next : c)) };
}

export function removeCondition(rule: Rule, id: string): Rule {
	return { ...rule, conditions: rule.conditions.filter((c) => c.id !== id) };
}

export function replaceChild(rule: Rule, id: string, next: Rule): Rule {
	return { ...rule, children: rule.children.map((c) => (c.id === id ? next : c)) };
}

export function removeChild(rule: Rule, id: string): Rule {
	return { ...rule, children: rule.children.filter((c) => c.id !== id) };
}

export function countConditions(rule: Rule): number {
	return rule.conditions.length + rule.children.reduce((sum, child) => sum + countConditions(child), 0);
}

export function allConditions(rule: Rule): Condition[] {
	return [...rule.conditions, ...rule.children.flatMap(allConditions)];
}

// The top-level rule a problem belongs to: the rule it names, or the one that
// holds the condition it names, however deep.
export function topRuleIdFor(rules: Rule[], problem: ProfileProblem): string | null {
	const holds = (rule: Rule): boolean =>
		rule.id === problem.rule_id ||
		rule.conditions.some((condition) => condition.id === problem.condition_id) ||
		rule.children.some(holds);
	return rules.find(holds)?.id ?? null;
}

export function firstCondition(rule: Rule): Condition | null {
	return rule.conditions.find((c) => c.field) ?? null;
}

// --- What the server sees -----------------------------------------------------------

// A condition with no field is still being made, and a group with nothing in it
// is too: sent as they are, an empty group would match every part. Both are
// left out of what the server compiles and saves. So, for a preview, is a
// condition with a field but nothing chosen yet: the preview then shows the rule
// as far as it is made, instead of dropping to nothing the moment a row is
// added. A save keeps such a condition, and the server says it is incomplete.
function withoutPlaceholders(rule: Rule, isGroup: boolean, skipUnchosen: boolean): Rule | null {
	const conditions = rule.conditions.filter(
		(condition) => condition.field && !(skipUnchosen && isEmptyValue(condition.value))
	);
	const children = rule.children
		.map((child) => withoutPlaceholders(child, true, skipUnchosen))
		.filter((child): child is Rule => child !== null);
	if (isGroup && conditions.length === 0 && children.length === 0) return null;
	return { ...rule, conditions, children };
}

export function documentFor(
	name: string,
	rules: Rule[],
	fallback: FallbackChoice,
	defaultCategoryId: string,
	// For a preview: leave out conditions with nothing chosen yet.
	forPreview = false,
	noBin: NoBinChoice = 'machine'
): ProfileDocument {
	return {
		name,
		default_category_id: defaultCategoryId,
		rules: rules.map((rule) => withoutPlaceholders(rule, false, forPreview) as Rule),
		fallback_mode: fallbackMode(fallback, noBin)
	};
}

// --- Problems and warnings -----------------------------------------------------------

export function isEmptyValue(value: unknown): boolean {
	if (value === null || value === undefined || value === '') return true;
	if (typeof value === 'number') return Number.isNaN(value);
	return Array.isArray(value) && value.length === 0;
}

export type Issues = {
	// By condition: what is wrong with that one condition.
	byCondition: Record<string, string>;
	// By rule: what is wrong with the rule as a whole (no condition to name).
	byRule: Record<string, string[]>;
};

export function groupProblems(problems: ProfileProblem[]): Issues {
	const byCondition: Record<string, string> = {};
	const byRule: Record<string, string[]> = {};
	for (const problem of problems) {
		if (problem.condition_id) byCondition[problem.condition_id] ??= problem.message;
		else if (problem.rule_id) (byRule[problem.rule_id] ??= []).push(problem.message);
	}
	return { byCondition, byRule };
}

export function groupBy<T>(items: T[], key: (item: T) => string | null): Record<string, T[]> {
	const out: Record<string, T[]> = {};
	for (const item of items) {
		const k = key(item);
		if (k) (out[k] ??= []).push(item);
	}
	return out;
}

// Two warnings that only say a rule is not finished yet. While someone is still
// choosing its values, they are the editor's empty state, not a warning.
const UNFINISHED = new Set(['condition_incomplete', 'no_conditions']);

export function isUnfinishedWarning(warning: ProfileWarning): boolean {
	return warning.code !== undefined && UNFINISHED.has(warning.code);
}

// "3 parts": the profile pages' own words for a count.
export { plural } from '$lib/profile-display';
