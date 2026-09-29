// The coverage ramp shared by the diversity donut and its trend line: none,
// started, halfway, nearly, full.
export function coverageColor(fill: number): string {
	if (fill >= 1) return 'var(--success)';
	if (fill >= 0.6) return 'color-mix(in srgb, var(--success) 60%, var(--warning))';
	if (fill >= 0.3) return 'var(--warning)';
	if (fill > 0) return 'var(--danger)';
	return 'var(--line)';
}
