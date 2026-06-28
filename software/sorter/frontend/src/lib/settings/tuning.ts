// Shared types + helpers for the Settings → Tuning pages. Every tuning page
// fetches `{ config, fields }` from its `/api/tuning/*` endpoint, where `fields`
// is the backend FIELD_META list, then renders one TuningParamRow per field.

export type TuningFieldMeta = {
	key: string;
	label: string;
	type: 'int' | 'float' | 'bool';
	default: number | boolean;
	section?: string;
	// Optional help text shown via the row's info icon (Settings tuning convention).
	description?: string;
};

export type TuningValues = Record<string, number | boolean>;

// A one-click named bundle of values for a tuning page. `values` is merged over
// the current form on apply, so a preset may set only the keys it cares about.
export type TuningPreset = {
	label: string;
	description: string;
	values: TuningValues;
};

// Group fields by their `section`, preserving first-seen section order. Shared by
// every tuning page so the section layout is identical across them.
export function groupTuningSections(
	fields: TuningFieldMeta[]
): { name: string; fields: TuningFieldMeta[] }[] {
	const order: string[] = [];
	const bySection = new Map<string, TuningFieldMeta[]>();
	for (const field of fields) {
		const section = field.section ?? 'Parameters';
		if (!bySection.has(section)) {
			bySection.set(section, []);
			order.push(section);
		}
		bySection.get(section)!.push(field);
	}
	return order.map((name) => ({ name, fields: bySection.get(name)! }));
}
