// A machine value as words for a person: "in_review" is "In review". Every
// label is in sentence case (the design system's docs/type.md).
export function sentence(value: string | null | undefined): string {
	const words = (value ?? '').replace(/_/g, ' ').trim();
	return words ? words[0].toUpperCase() + words.slice(1).toLowerCase() : '';
}
