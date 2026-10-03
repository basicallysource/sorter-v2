// Sample data for the Profiles page: real catalog parts, colors and
// categories (public catalog data, the pictures served by the Rebrickable
// CDN), in bins named plainly. The shapes are what Hive sends for a compiled
// profile (docs/components.md#profiles).
import type { Bin, BinSample } from '$lib/components/ProfileBin.svelte';
import type { BinCondition, BinConditions } from '$lib/components/ConditionList.svelte';

const pic = (path: string) => `https://cdn.rebrickable.com/media/parts/${path}`;

// BrickLink IDs, with the Rebrickable number where it differs.
export const parts = {
	brick2x4: {
		part_num: '3001',
		rb_part_num: '3001',
		name: 'Brick 2 x 4',
		img_url: pic('elements/300121.jpg')
	},
	brick2x3: {
		part_num: '3002',
		rb_part_num: '3002',
		name: 'Brick 2 x 3',
		img_url: pic('elements/300221.jpg')
	},
	brick2x2: {
		part_num: '3003',
		rb_part_num: '3003',
		name: 'Brick 2 x 2',
		img_url: pic('elements/300301.jpg')
	},
	brick1x2: {
		part_num: '3004',
		rb_part_num: '3004',
		name: 'Brick 1 x 2',
		img_url: pic('elements/300401.jpg')
	},
	brick1x1: {
		part_num: '3005',
		rb_part_num: '3005',
		name: 'Brick 1 x 1',
		img_url: pic('elements/300501.jpg')
	},
	brick1x4: {
		part_num: '3010',
		rb_part_num: '3010a',
		name: 'Brick 1 x 4 with Bottom Tubes, Lowered Center Cross Support',
		img_url: pic('photos/15/3010a-15-7652bcde-370a-4149-955c-88b61f73cc8c.jpg')
	},
	plate2x4: {
		part_num: '3020',
		rb_part_num: '3020',
		name: 'Plate 2 x 4',
		img_url: pic('elements/302026.jpg')
	},
	plate2x3: {
		part_num: '3021',
		rb_part_num: '3021',
		name: 'Plate 2 x 3',
		img_url: pic('elements/302126.jpg')
	},
	tile1x2: {
		part_num: '3069',
		rb_part_num: '3069b',
		name: 'Tile 1 x 2 with Groove',
		img_url: pic('elements/306901.jpg')
	},
	slope: {
		part_num: '3040',
		rb_part_num: '3040b',
		name: 'Slope 45° 2 x 1 with Bottom Pin',
		img_url: pic('elements/4211135.jpg')
	},
	pin: {
		part_num: '2780',
		rb_part_num: '61332',
		name: 'Technic Pin with Friction Ridges Lengthwise with No Center Slots',
		img_url: pic('elements/6279875.jpg')
	},
	jumper: {
		part_num: '3794a',
		rb_part_num: '3794a',
		name: 'Plate Special 1 x 2 with 1 Stud without Groove (Jumper)',
		img_url: pic('ldraw/0/3794a.png')
	},
	bracket: {
		part_num: '99781',
		rb_part_num: '99781',
		name: 'Bracket 1 x 2 - 1 x 2',
		img_url: pic('elements/4654582.jpg')
	},
	roundTile: {
		part_num: '98138',
		rb_part_num: '98138',
		name: 'Tile Round 1 x 1',
		img_url: pic('elements/6139403.jpg')
	},
	corner: {
		part_num: '2420',
		rb_part_num: '2420',
		name: 'Plate 2 x 2 Corner',
		img_url: pic('elements/242026.jpg')
	},
	// A part the catalog has no picture for.
	noPicture: {
		part_num: '3794b',
		rb_part_num: '3794b',
		name: 'Plate Special 1 x 2 with 1 Stud with Groove (Jumper)',
		img_url: null
	}
} satisfies Record<string, BinSample>;

// A catalog color's name and RGB (six hex digits, no #).
export const colors = {
	red: { name: 'Red', rgb: 'C91A09' },
	darkRed: { name: 'Dark Red', rgb: '720E0F' },
	sandRed: { name: 'Sand Red', rgb: 'D67572' },
	salmon: { name: 'Salmon', rgb: 'F2705E' },
	lightSalmon: { name: 'Light Salmon', rgb: 'FEBABD' },
	rust: { name: 'Rust', rgb: 'B31004' },
	pearlRed: { name: 'Pearl Red', rgb: 'D60026' },
	chromeRed: { name: 'Chrome Red', rgb: 'CE3021' },
	blue: { name: 'Blue', rgb: '0055BF' },
	yellow: { name: 'Yellow', rgb: 'F2CD37' },
	green: { name: 'Green', rgb: '237841' },
	white: { name: 'White', rgb: 'FFFFFF' },
	transClear: { name: 'Trans-Clear', rgb: 'FCFCFC' },
	black: { name: 'Black', rgb: '05131D' },
	lightBluishGray: { name: 'Light Bluish Gray', rgb: 'A0A5A9' },
	darkBluishGray: { name: 'Dark Bluish Gray', rgb: '6C6E68' },
	tan: { name: 'Tan', rgb: 'E4CD9E' },
	transRed: { name: 'Trans-Red', rgb: 'C91A09' },
	transYellow: { name: 'Trans-Yellow', rgb: 'F5CD2A' },
	transBlue: { name: 'Trans-Dark Blue', rgb: '0020A0' },
	transGreen: { name: 'Trans-Green', rgb: '237841' },
	transOrange: { name: 'Trans-Orange', rgb: 'F08F1C' }
};

const reds = [
	colors.red,
	colors.darkRed,
	colors.sandRed,
	colors.salmon,
	colors.lightSalmon,
	colors.rust,
	colors.pearlRed,
	colors.chromeRed
];

function category(
	id: string,
	field_label: string,
	op: string,
	op_label: string,
	names: string[]
): BinCondition {
	return {
		id,
		field: 'bl_category_id',
		field_label,
		op,
		op_label,
		values: names.map((label, i) => ({ value: i + 1, label }))
	};
}

function color(
	id: string,
	op: string,
	op_label: string,
	list: Array<{ name: string; rgb: string }>
): BinCondition {
	return {
		id,
		field: 'color_id',
		field_label: 'Color',
		op,
		op_label,
		values: list.map((c, i) => ({
			value: i + 1,
			label: c.name,
			rgb: c.rgb,
			bricklink_id: String(i + 1)
		}))
	};
}

function partValue(part: BinSample) {
	return {
		value: part.part_num,
		label: part.name,
		img_url: part.img_url,
		part_num: part.rb_part_num ?? part.part_num,
		bricklink_id: part.part_num
	};
}

const brickCategory = category('c1', 'BrickLink category', 'eq', 'is', ['Brick']);

const transparent = [
	colors.transClear,
	colors.transRed,
	colors.transYellow,
	colors.transBlue,
	colors.transGreen,
	colors.transOrange
];

export const conditions = {
	category: { mode: 'all', items: [brickCategory], groups: [] } satisfies BinConditions,
	reds: {
		mode: 'all',
		items: [brickCategory, color('c2', 'in', 'is one of', reds)],
		groups: []
	} satisfies BinConditions,
	onePart: {
		mode: 'all',
		items: [
			{
				id: 'c3',
				field: 'bricklink_id',
				field_label: 'BrickLink ID',
				op: 'eq',
				op_label: 'is',
				values: [partValue(parts.brick2x4)]
			}
		],
		groups: []
	} satisfies BinConditions,
	parts: {
		mode: 'all',
		items: [
			{
				id: 'c4',
				field: 'bricklink_id',
				field_label: 'BrickLink ID',
				op: 'in',
				op_label: 'is one of',
				values: [parts.brick2x4, parts.brick2x3, parts.brick2x2, parts.brick1x2].map(partValue)
			}
		],
		groups: []
	} satisfies BinConditions,
	anyOf: {
		mode: 'any',
		items: [
			{
				id: 'c5',
				field: 'name',
				field_label: 'Name',
				op: 'regex',
				op_label: 'matches',
				values: [{ value: 'stud.*side|headlight', label: 'stud.*side|headlight' }]
			},
			category('c6', 'BrickLink category', 'eq', 'is', ['Bracket'])
		],
		groups: []
	} satisfies BinConditions,
	nested: {
		mode: 'all',
		items: [
			category('c7', 'BrickLink category', 'in', 'is one of', ['Plate', 'Plate, Modified', 'Tile']),
			{
				id: 'c8',
				field: 'bl_catalog_dim_x',
				field_label: 'Length',
				op: 'lte',
				op_label: 'is at most',
				values: [{ value: 4, label: '4 studs' }]
			}
		],
		groups: [
			{
				id: 'g1',
				mode: 'any',
				items: [
					color('c9', 'in', 'is one of', [colors.white, colors.transClear]),
					{
						id: 'c10',
						field: 'bl_price_avg',
						field_label: 'Average price',
						op: 'gte',
						op_label: 'is at least',
						values: [{ value: 0.25, label: '$0.25' }]
					}
				],
				groups: []
			}
		]
	} satisfies BinConditions,
	transparent: {
		mode: 'all',
		items: [color('c15', 'in', 'is one of', transparent)],
		groups: []
	} satisfies BinConditions,
	incomplete: {
		mode: 'all',
		items: [
			category('c11', 'BrickLink category', 'eq', 'is', ['Slope']),
			{
				id: 'c12',
				field: 'color_id',
				field_label: 'Color',
				op: 'in',
				op_label: 'is one of',
				values: [{ value: null, label: '' }],
				invalid: true
			}
		],
		groups: []
	} satisfies BinConditions
};

const examples = (list: BinSample[]) => list.slice(0, 6);

export const bins = {
	reds: {
		name: 'Red bricks',
		kind: 'rule',
		image_url: parts.brick2x4.img_url,
		conditions: conditions.reds,
		part_count: 72,
		color_count: 8,
		samples: examples([
			parts.brick2x4,
			parts.brick2x3,
			parts.brick2x2,
			parts.brick1x2,
			parts.brick1x1,
			parts.brick1x4
		])
	},
	transparent: {
		name: 'Transparent',
		kind: 'rule',
		image_url: parts.plate2x4.img_url,
		conditions: conditions.transparent,
		part_count: 81234,
		any_part: true,
		color_count: 6,
		colors: transparent.map((c, i) => ({ id: String(i + 1), name: c.name, rgb: c.rgb })),
		samples: examples([
			parts.plate2x4,
			parts.brick1x2,
			parts.tile1x2,
			parts.slope,
			parts.roundTile,
			parts.corner
		])
	},
	onePart: {
		name: 'Brick 2 x 4',
		kind: 'rule',
		image_url: parts.brick2x4.img_url,
		conditions: conditions.onePart,
		part_count: 1,
		samples: examples([parts.brick2x4])
	},
	kit: {
		name: 'Starter kit',
		kind: 'kit',
		image_url: parts.brick2x3.img_url,
		part_count: 14,
		kit: { line_count: 14, total_quantity: 96 },
		samples: [
			{ ...parts.brick2x4, color_name: 'Red', quantity: 8 },
			{ ...parts.brick2x4, color_name: 'Blue', quantity: 6 },
			{ ...parts.brick2x2, color_name: 'Yellow', quantity: 10 },
			{ ...parts.brick1x2, color_name: 'White', quantity: 12 },
			{ ...parts.plate2x4, color_name: 'Dark Bluish Gray', quantity: 4 },
			{ ...parts.tile1x2, color_name: 'Black', quantity: 16 }
		]
	},
	tiles: {
		name: 'Tile',
		kind: 'fallback',
		image_url: parts.tile1x2.img_url,
		part_count: 318,
		samples: examples([
			parts.tile1x2,
			parts.roundTile,
			parts.plate2x3,
			parts.slope,
			parts.corner,
			parts.jumper
		])
	},
	gray: {
		name: 'Dark Bluish Gray',
		kind: 'fallback',
		rgb: '6C6E68',
		part_count: null,
		samples: []
	},
	rest: {
		name: 'Everything else',
		kind: 'default',
		part_count: 22388,
		samples: examples([
			parts.pin,
			parts.jumper,
			parts.bracket,
			parts.slope,
			parts.roundTile,
			parts.noPicture
		])
	},
	shadowed: {
		name: 'Red plates',
		kind: 'rule',
		image_url: parts.plate2x3.img_url,
		conditions: {
			mode: 'all',
			items: [
				category('c13', 'BrickLink category', 'eq', 'is', ['Plate']),
				color('c14', 'in', 'is one of', [colors.red, colors.darkRed])
			],
			groups: []
		} satisfies BinConditions,
		part_count: 0,
		color_count: 2,
		samples: []
	},
	gaps: {
		name: 'Red slopes',
		kind: 'rule',
		conditions: conditions.incomplete,
		part_count: 0,
		samples: []
	},
	legacy: { name: 'Bulk' }
} satisfies Record<string, Bin>;

export const warnings = {
	shadowed: ['Rules above this one already take every part it matches.'],
	gaps: ['A condition here is incomplete, so this rule takes nothing until it is fixed.'],
	kit: ['3 of this kit’s lines have no color, so a piece of any color counts toward them.']
};

// A profile's bins in order, for the row layout.
export const order: Array<{
	id: keyof typeof bins;
	bin: Bin;
	warnings?: string[];
	progress?: { found: number; needed: number };
}> = [
	{ id: 'onePart', bin: bins.onePart },
	{ id: 'kit', bin: bins.kit, warnings: warnings.kit, progress: { found: 41, needed: 96 } },
	{ id: 'reds', bin: bins.reds },
	{ id: 'transparent', bin: bins.transparent },
	{ id: 'shadowed', bin: bins.shadowed, warnings: warnings.shadowed },
	{ id: 'tiles', bin: bins.tiles },
	{ id: 'gray', bin: bins.gray },
	{ id: 'rest', bin: bins.rest }
];
