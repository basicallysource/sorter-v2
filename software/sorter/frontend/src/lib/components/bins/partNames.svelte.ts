// Names for the parts bins are named by ("3001" -> "Brick 2 x 4"), as the
// machine last recorded them. Reactive, so a bin label updates once they load.
let names = $state<Record<string, string>>({});

export function setPartNames(next: unknown): void {
	if (!next || typeof next !== 'object') return;
	names = next as Record<string, string>;
}

export function partName(partId: string): string | null {
	return names[partId] ?? null;
}
