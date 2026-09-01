// The link page prefills the machine name, so whatever sits in that field is
// the name most people keep. It used to be the constant "Lego Sorter", which
// made every fleet a wall of identical names; now a Sorter that already knows
// what it is called sends that along, and this is the fallback when it does
// not — an older Sorter, or someone who opened the link page directly.
//
// Same words the Sorter draws its Tailscale device name from
// (software/sorter/backend/server/machine_naming.py), so a machine named here
// and a machine named at firstboot read as the same family.

const LEGO_COLORS = [
	'Aqua',
	'Azure',
	'Black',
	'Blue',
	'Bright Green',
	'Bright Pink',
	'Brown',
	'Coral',
	'Dark Azure',
	'Dark Blue',
	'Dark Brown',
	'Dark Gray',
	'Dark Green',
	'Dark Orange',
	'Dark Pink',
	'Dark Purple',
	'Dark Red',
	'Dark Tan',
	'Dark Turquoise',
	'Gray',
	'Green',
	'Lavender',
	'Light Aqua',
	'Light Blue',
	'Light Gray',
	'Light Pink',
	'Light Purple',
	'Light Yellow',
	'Lime',
	'Magenta',
	'Medium Azure',
	'Medium Blue',
	'Medium Green',
	'Medium Lavender',
	'Medium Nougat',
	'Nougat',
	'Olive',
	'Orange',
	'Pink',
	'Purple',
	'Red',
	'Reddish Brown',
	'Sand Blue',
	'Sand Green',
	'Tan',
	'Teal',
	'Warm Gold',
	'White',
	'Yellow'
];

const LEGO_PIECES = [
	'Antenna',
	'Arch',
	'Axle',
	'Baseplate',
	'Beam',
	'Bracket',
	'Brick',
	'Bushing',
	'Clip',
	'Cone',
	'Cylinder',
	'Dish',
	'Dome',
	'Door',
	'Fence',
	'Flag',
	'Gear',
	'Grille',
	'Hinge',
	'Hose',
	'Jumper',
	'Ladder',
	'Lever',
	'Minifig',
	'Panel',
	'Pin',
	'Plate',
	'Propeller',
	'Rail',
	'Ramp',
	'Rod',
	'Roof',
	'Slope',
	'Sprocket',
	'Stud',
	'Technic',
	'Tile',
	'Tube',
	'Turntable',
	'Wedge',
	'Wheel',
	'Windscreen',
	'Wing'
];

function pick(words: string[]): string {
	return words[Math.floor(Math.random() * words.length)];
}

export function randomMachineName(): string {
	return `${pick(LEGO_COLORS)} ${pick(LEGO_PIECES)}`;
}
