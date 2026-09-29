// The choices still open (docs/decisions.md, Open): each is a data attribute
// on <html> that app.css reads, remembered in this browser. app.html applies
// the saved ones before first paint. When one is decided, its winner becomes
// the default in app.css and the dimension leaves this list.

export type Dimension = 'font' | 'labels' | 'corners' | 'buttons' | 'density';

export type Option = {
	// The data attribute's value.
	value: string;
	letter: string;
	name: string;
	detail?: string;
	today?: boolean;
};

export const dimensions: { key: Dimension; name: string; options: Option[] }[] = [
	{
		key: 'font',
		name: 'Typeface',
		options: [
			{ value: 'a', letter: 'A', name: 'IBM Plex Sans', detail: 'with IBM Plex Mono', today: true },
			{ value: 'b', letter: 'B', name: 'Inter', detail: 'with JetBrains Mono' },
			{ value: 'c', letter: 'C', name: 'Geist', detail: 'with Geist Mono' },
			{ value: 'd', letter: 'D', name: 'Instrument Sans', detail: 'with DM Mono' },
			{ value: 'e', letter: 'E', name: 'Figtree', detail: 'with JetBrains Mono' },
			{ value: 'f', letter: 'F', name: 'Public Sans', detail: 'with Roboto Mono' },
			{ value: 'g', letter: 'G', name: 'Schibsted Grotesk', detail: 'with Geist Mono' }
		]
	},
	{
		key: 'labels',
		name: 'Labels and numbers',
		options: [
			{ value: 'a', letter: 'A', name: 'Capitals, mono numbers', today: true },
			{ value: 'b', letter: 'B', name: "Capitals, the typeface's numbers" },
			{ value: 'c', letter: 'C', name: "Sentence case, the typeface's numbers" }
		]
	},
	{
		key: 'corners',
		name: 'Corners',
		options: [
			{ value: '0', letter: 'A', name: 'Square', today: true },
			{ value: '4', letter: 'B', name: '4px' },
			{ value: '6', letter: 'C', name: '6px' },
			{ value: '8', letter: 'D', name: '8px' },
			{ value: 'pill', letter: 'E', name: 'Pill buttons', detail: '8px elsewhere' }
		]
	},
	{
		key: 'buttons',
		name: 'Buttons',
		options: [
			{ value: 'a', letter: 'A', name: 'Solid primary, outlined secondary', today: true },
			{ value: 'b', letter: 'B', name: 'Solid primary, soft secondary' },
			{ value: 'c', letter: 'C', name: 'Ink primary, soft secondary' },
			{ value: 'd', letter: 'D', name: 'Outlined' },
			{ value: 'e', letter: 'E', name: 'Tinted' }
		]
	},
	{
		key: 'density',
		name: 'Density',
		options: [
			{ value: 'compact', letter: 'A', name: 'Compact', detail: '36px controls', today: true },
			{ value: 'roomy', letter: 'B', name: 'Roomy', detail: '40px controls' }
		]
	}
];

const DEFAULTS: Record<Dimension, string> = {
	font: 'a',
	labels: 'a',
	corners: '0',
	buttons: 'a',
	density: 'compact'
};

function read(key: Dimension): string {
	try {
		return localStorage.getItem(`choice-${key}`) ?? DEFAULTS[key];
	} catch {
		return DEFAULTS[key];
	}
}

class Choices {
	current = $state<Record<Dimension, string>>({
		font: read('font'),
		labels: read('labels'),
		corners: read('corners'),
		buttons: read('buttons'),
		density: read('density')
	});

	constructor() {
		$effect.root(() => {
			$effect(() => {
				for (const [key, value] of Object.entries(this.current)) {
					document.documentElement.dataset[key] = value;
				}
			});
		});
	}

	set(key: Dimension, value: string) {
		this.current[key] = value;
		try {
			localStorage.setItem(`choice-${key}`, value);
		} catch {
			// The choice lasts the visit.
		}
	}

	reset() {
		for (const key of Object.keys(DEFAULTS) as Dimension[]) this.set(key, DEFAULTS[key]);
	}

	/** The letters chosen, e.g. "Typeface B, Labels C, ...". */
	summary(): string {
		return dimensions
			.map((d) => `${d.name} ${d.options.find((o) => o.value === this.current[d.key])?.letter}`)
			.join(', ');
	}
}

export const choices = new Choices();
