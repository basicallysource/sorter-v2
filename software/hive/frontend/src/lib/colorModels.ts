/** How a colour model's answer reads on the labeling pages. */

// The confidence bands, in one place: at or above HIGH is High, at or above
// MEDIUM is Medium, below is Low.
export const HIGH = 0.9;
export const MEDIUM = 0.6;

export type Band = 'High' | 'Medium' | 'Low';

export function band(confidence: number): Band {
	return confidence >= HIGH ? 'High' : confidence >= MEDIUM ? 'Medium' : 'Low';
}

export function bandTone(b: Band): 'success' | 'warning' | 'danger' {
	return b === 'High' ? 'success' : b === 'Medium' ? 'warning' : 'danger';
}

// The band as the colour of the number alone, where a badge is too wide.
export function bandText(b: Band): string {
	return b === 'High' ? 'text-success-ink' : b === 'Medium' ? 'text-warning-ink' : 'text-danger-ink';
}

export function percent(confidence: number): string {
	return `${Math.round(confidence * 100)}%`;
}

/** A model's registry name as a short label: "colorpred-v3" is "Color v3". */
export function modelLabel(name: string): string {
	const m = /^colorpred-(.+)$/i.exec(name);
	return m ? `Color ${m[1]}` : name;
}
