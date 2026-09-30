// How the machine is drawn: the materials for each look the 3D page can take.
// Every look uses the same three surfaces (the body, the dark parts, the bins)
// and the same colours from the theme, so the look changes nothing else on the
// page. Lines, where a look has them, are the creases of the CAD's surfaces.
import {
	CanvasTexture,
	Color,
	DataTexture,
	LineBasicMaterial,
	type Material,
	MeshBasicMaterial,
	MeshMatcapMaterial,
	MeshStandardMaterial,
	MeshToonMaterial,
	NearestFilter,
	RedFormat,
	SRGBColorSpace
} from 'three';

export type LookName = 'lit' | 'flat' | 'flat-lines' | 'clay' | 'drawing' | 'cad';

export const LOOKS: { name: LookName; label: string; lines: boolean }[] = [
	{ name: 'lit', label: 'Lit', lines: false },
	{ name: 'flat', label: 'Flat', lines: false },
	{ name: 'flat-lines', label: 'Flat with lines', lines: true },
	{ name: 'clay', label: 'Clay', lines: false },
	{ name: 'drawing', label: 'Drawing', lines: true },
	{ name: 'cad', label: 'CAD colours', lines: false }
];

export type Palette = { body: Color; dark: Color; bin: Color; line: Color };

export type LookMaterials = {
	body: Material;
	dark: Material;
	// White, so each bin's instance colour is its colour.
	bin: Material;
	line: LineBasicMaterial;
};

let toonRamp: DataTexture | null = null;
let matcap: CanvasTexture | null = null;

/** Three bands of light, for the flat looks. */
function ramp() {
	if (!toonRamp) {
		toonRamp = new DataTexture(new Uint8Array([95, 150, 205]), 3, 1, RedFormat);
		toonRamp.minFilter = toonRamp.magFilter = NearestFilter;
		toonRamp.needsUpdate = true;
	}
	return toonRamp;
}

/** A soft studio light from above and to the left, for the clay look. */
function clay() {
	if (!matcap) {
		const size = 128;
		const canvas = document.createElement('canvas');
		canvas.width = canvas.height = size;
		const g = canvas.getContext('2d')!;
		const light = g.createRadialGradient(size * 0.36, size * 0.3, 2, size / 2, size / 2, size / 2);
		light.addColorStop(0, '#ffffff');
		light.addColorStop(0.55, '#c9c9c9');
		light.addColorStop(1, '#6f6f6f');
		g.fillStyle = light;
		g.fillRect(0, 0, size, size);
		matcap = new CanvasTexture(canvas);
		matcap.colorSpace = SRGBColorSpace;
	}
	return matcap;
}

export function makeLook(name: LookName, p: Palette): LookMaterials {
	const line = new LineBasicMaterial({ color: p.line });
	const surface = (color: Color, rough: number) => {
		switch (name) {
			case 'flat':
			case 'flat-lines':
				return new MeshToonMaterial({ color, gradientMap: ramp() });
			case 'clay':
				return new MeshMatcapMaterial({ color, matcap: clay() });
			case 'drawing':
				return new MeshBasicMaterial({ color });
			case 'cad':
				return new MeshStandardMaterial({ color, roughness: rough });
			default:
				return new MeshStandardMaterial({ color, roughness: rough });
		}
	};
	const white = new Color(1, 1, 1);
	const body = surface(name === 'cad' ? white : p.body, 0.85);
	const dark = surface(name === 'cad' ? white : p.dark, 0.7);
	if (name === 'cad') {
		(body as MeshStandardMaterial).vertexColors = true;
		(dark as MeshStandardMaterial).vertexColors = true;
	}
	// Lines sit on the faces they edge without fighting them for depth.
	for (const m of [body, dark]) {
		m.polygonOffset = true;
		m.polygonOffsetFactor = 1;
		m.polygonOffsetUnits = 1;
	}
	const bin = surface(white, 0.9);
	return { body, dark, bin, line };
}
