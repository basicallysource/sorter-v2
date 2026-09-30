// What a condition's field decides about the rest of its row: which operators
// to offer, what kind of editor its value needs, and what a value turns into
// when the field or the operator changes. Pure, so the row stays a few lines.

import type { ProfileField } from '$lib/api';
import type { Condition } from './rules';

// What the value of a condition is, and so how it is edited: parts are found by
// searching, colors and categories are chosen from a list, numbers have a unit,
// text is typed, a yes or no is a switch between two.
export type ValueKind = 'part' | 'color' | 'category' | 'number' | 'text' | 'yesno';

export const OP_WORDS: Record<string, string> = {
	eq: 'is',
	neq: 'is not',
	in: 'is one of',
	not_in: 'is not one of',
	contains: 'contains',
	regex: 'matches',
	gte: 'is at least',
	lte: 'is at most'
};

export function valueKind(field: ProfileField | undefined): ValueKind {
	if (!field) return 'text';
	if (field.type === 'bool') return 'yesno';
	if (field.ref === 'part' || field.ref === 'bl_part') return 'part';
	if (field.ref === 'color') return 'color';
	if (field.ref === 'bl_category' || field.ref === 'rb_category') return 'category';
	if (field.type === 'int' || field.type === 'float') return 'number';
	return 'text';
}

// "Is one of" and "is not one of" take a list; every other operator takes one value.
export function isMulti(op: string): boolean {
	return op === 'in' || op === 'not_in';
}

// Parts, colors and categories are almost always several, so a new condition on
// one starts as "is one of".
export function defaultOp(field: ProfileField): string {
	const kind = valueKind(field);
	const several = kind === 'part' || kind === 'color' || kind === 'category';
	if (several && field.ops.includes('in')) return 'in';
	return field.ops[0] ?? 'eq';
}

export function emptyValue(op: string): unknown {
	return isMulti(op) ? [] : '';
}

export function toList(value: unknown): unknown[] {
	if (Array.isArray(value)) return value;
	return value === '' || value === null || value === undefined ? [] : [value];
}

// The same value, for another operator: a list keeps its first item when the
// operator takes only one, and one value becomes a list of one.
export function valueForOp(value: unknown, toOp: string): unknown {
	const list = toList(value);
	if (isMulti(toOp)) return list;
	return list.length > 0 ? list[0] : '';
}

// Two fields name values of the same sort (two BrickLink category fields, or
// the year a part was first and last made), so a value carries over from one to
// the other.
export function sharesValues(a: ProfileField | undefined, b: ProfileField | undefined): boolean {
	if (!a || !b) return false;
	return valueKind(a) === valueKind(b) && a.ref === b.ref && a.type === b.type;
}

// The condition once its field is another: an operator the new field takes, and
// a value that still means something.
export function withField(condition: Condition, previous: ProfileField | undefined, next: ProfileField): Condition {
	const op = next.ops.includes(condition.op) ? condition.op : defaultOp(next);
	let value: unknown;
	if (valueKind(next) === 'yesno') value = 1;
	else if (sharesValues(previous, next)) value = valueForOp(condition.value, op);
	else value = emptyValue(op);
	return { ...condition, field: next.field, op, value };
}

export function withOp(condition: Condition, op: string): Condition {
	return { ...condition, op, value: valueForOp(condition.value, op) };
}

// --- Choosing a field --------------------------------------------------------------

export type FieldOption = { value: string; label: string; hint: string };

// The fields as a list to choose from: grouped as the server groups them, in the
// order each group first appears.
export function fieldOptions(fields: ProfileField[]): FieldOption[] {
	const groups: string[] = [];
	for (const field of fields) if (!groups.includes(field.group)) groups.push(field.group);
	const sorted = [...fields].sort((a, b) => groups.indexOf(a.group) - groups.indexOf(b.group));
	return sorted.map((field) => ({ value: field.field, label: field.label, hint: field.group }));
}

export function opOptions(
	field: ProfileField | undefined,
	current: string,
	words: Record<string, string> = OP_WORDS
): { value: string; label: string }[] {
	const ops = field ? [...field.ops] : [];
	if (current && !ops.includes(current)) ops.unshift(current);
	return ops.map((op) => ({ value: op, label: words[op] ?? OP_WORDS[op] ?? op }));
}

// --- What a value asks of the person -----------------------------------------------

export function emptyMessage(kind: ValueKind, multi: boolean): string {
	switch (kind) {
		case 'part':
			return multi ? 'Pick at least one part.' : 'Pick a part.';
		case 'color':
			return multi ? 'Pick at least one color.' : 'Pick a color.';
		case 'category':
			return multi ? 'Pick at least one category.' : 'Pick a category.';
		case 'number':
			return multi ? 'Add at least one number.' : 'Enter a number.';
		case 'yesno':
			return 'Choose yes or no.';
		default:
			return multi ? 'Add at least one value.' : 'Enter some text.';
	}
}

export function valuePlaceholder(kind: ValueKind, op: string): string {
	if (kind === 'text') {
		if (op === 'regex') return 'A pattern, such as ^Brick 2 x';
		if (op === 'contains') return 'Text to look for';
		return isMulti(op) ? 'Type a value and press Enter' : 'The exact text';
	}
	if (kind === 'number') return isMulti(op) ? 'Type a number and press Enter' : 'A number';
	return '';
}
