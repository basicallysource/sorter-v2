/** How a sorter's training run reads on Hive's pages. */

import type { TrainingRunColor } from '$lib/api';
import { sentence } from '$lib/text';

/** "Red", "Red and Blue", "Red, Blue and Yellow". */
export function colorNames(colors: TrainingRunColor[]): string {
	const names = colors.map((c) => c.name ?? `Color ${c.id}`);
	if (names.length <= 1) return names[0] ?? '';
	return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** What the run was for: "Color run: Red and Blue". */
export function runPurpose(mode: string | null, colors: TrainingRunColor[]): string {
	const kind = mode ? `${sentence(mode)} run` : 'Training run';
	return colors.length > 0 ? `${kind}: ${colorNames(colors)}` : kind;
}

/** How a piece's label was decided, from its run. */
export function labelSourceText(source: string | null): string {
	if (source === 'run') return "The run's one color";
	if (source === 'prediction') return "The machine's first color guess that is one of the run's colors";
	if (source === 'nearest') return "The run's color nearest the machine's own";
	return 'The run gave it no color';
}
