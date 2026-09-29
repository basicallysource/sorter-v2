// The rules, as the overview lists them. docs/rules.md is the full text;
// keep the two in the same order with the same titles.

export const rules = [
	{
		id: 'planes',
		title: 'Planes, not outlines',
		summary:
			'A panel is told apart from the page by its fill. Planes nest one way only: canvas, surface, well.'
	},
	{
		id: 'double-lines',
		title: 'Two lines never meet',
		summary:
			'No double borders, anywhere. A line sits between two items, never around a box inside a box.'
	},
	{
		id: 'spinner',
		title: 'One loading indicator',
		summary: 'Anything loading shows the Spinner, and nothing else spins.'
	},
	{
		id: 'state',
		title: 'State is a fill',
		summary: 'Hover, selected and pressed change the fill. No line gets thicker to show state.'
	},
	{
		id: 'color',
		title: 'Color carries meaning',
		summary:
			'Neutrals for structure, the primary for what you act on, status colors for status only.'
	},
	{
		id: 'square',
		title: 'Square corners',
		summary: 'Nothing is rounded but a status dot.'
	},
	{
		id: 'text',
		title: 'Readable is 14px',
		summary: 'Anything someone has to read is 14px or larger; 12px is for labels and badges.'
	},
	{
		id: 'tokens',
		title: 'Tokens, never raw colors',
		summary: 'Markup names a token, so both modes and every primary come for free.'
	},
	{
		id: 'icons',
		title: 'Lucide icons, beside words',
		summary: 'Every icon is Lucide, next to a word or with a label.'
	},
	{
		id: 'copy',
		title: 'Copy the component',
		summary: 'Apps copy these files as they are. A new look is made here first.'
	}
];
