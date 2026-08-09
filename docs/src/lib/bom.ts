// Turns a WireViz `<name>.bom.tsv` into a table element.
//
// The TSVs are build artifacts in the assets bucket, never in git, so this
// runs in the browser rather than at build time. See the effect in
// routes/[...path]/+page.svelte for why.

// WireViz emits `Id, Description, Qty, Unit, Designators` and, when a part
// carries them, `Manufacturer, MPN`.
const CELL_CLASS: Record<string, string> = {
	id: 'bom-num',
	qty: 'bom-num',
	unit: 'bom-unit'
};

export function parseBomTsv(text: string): string[][] {
	return text
		.split(/\r?\n/)
		.filter((line) => line.trim() !== '')
		.map((line) => line.split('\t'));
}

// Cells are frequently empty and a row can be short a trailing column, so the
// width is the widest row and every cell is padded out to it.
export function buildBomTable(rows: string[][], label: string): HTMLTableElement {
	const cols = Math.max(...rows.map((r) => r.length));
	const head = Array.from({ length: cols }, (_, i) => (rows[0][i] ?? '').trim());

	const table = document.createElement('table');
	table.className = 'bom-table';
	table.setAttribute('aria-label', label);

	const thead = document.createElement('thead');
	const headRow = document.createElement('tr');
	for (const name of head) {
		const th = document.createElement('th');
		th.textContent = name;
		th.className = CELL_CLASS[name.toLowerCase()] ?? '';
		headRow.appendChild(th);
	}
	thead.appendChild(headRow);
	table.appendChild(thead);

	const tbody = document.createElement('tbody');
	for (const row of rows.slice(1)) {
		const tr = document.createElement('tr');
		for (let i = 0; i < cols; i++) {
			const td = document.createElement('td');
			td.textContent = (row[i] ?? '').trim();
			td.className = CELL_CLASS[head[i].toLowerCase()] ?? '';
			tr.appendChild(td);
		}
		tbody.appendChild(tr);
	}
	table.appendChild(tbody);
	return table;
}
