import argparse
import json
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

SCRIPT_DIR = Path(__file__).resolve().parent
CLIENT_DIR = SCRIPT_DIR.parent
PROJECT_DIR = CLIENT_DIR.parent
DEFAULT_PORT = 8120

sys.path.insert(0, str(CLIENT_DIR))

from dotenv import load_dotenv

load_dotenv(PROJECT_DIR / ".env")

from blob_manager import getBinCategories, setBinCategories
from global_config import mkGlobalConfig
from irl.bin_layout import (
    BinLayoutConfig,
    DEFAULT_BIN_LAYOUT,
    LayerConfig,
    applyCategories,
    layoutMatchesCategories,
    mkLayoutFromConfig,
)
from irl.parse_user_toml import loadMachineConfig


HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Arrange Bins</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f4f4;
      color: #111;
    }
    .app {
      display: flex;
      gap: 12px;
      min-height: 100vh;
      padding: 12px;
    }
    .main_panel {
      flex: 1;
      min-width: 0;
    }
    .top_row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 4px;
    }
    .row_title {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    .subtle {
      color: #666;
      font-size: 12px;
      margin: 0;
    }
    .badge {
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 600;
      border: 1px solid #f0c24f;
      background: #fff7dc;
      color: #8a5a00;
    }
    .badge.hidden {
      display: none;
    }
    .layer {
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 8px;
      margin-top: 10px;
      padding: 10px;
    }
    .layer_header {
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 8px;
    }
    .sections_row {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 4px;
    }
    .section {
      min-width: 180px;
      border: 1px solid #e5e5e5;
      border-radius: 6px;
      padding: 8px;
      background: #fafafa;
    }
    .section_title {
      font-size: 12px;
      color: #555;
      margin-bottom: 6px;
    }
    .bin {
      border: 1px solid #ddd;
      border-radius: 6px;
      padding: 6px;
      margin-bottom: 6px;
      background: #fff;
      cursor: pointer;
    }
    .bin.selected {
      border-color: #1e67ff;
      box-shadow: 0 0 0 1px #1e67ff;
    }
    .bin_label {
      font-size: 12px;
      margin-bottom: 4px;
      color: #333;
    }
    .bin_current {
      font-size: 11px;
      color: #444;
      margin-bottom: 6px;
      word-break: break-word;
    }
    .bin_controls {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .bin_controls select {
      flex: 1;
      width: 100%;
      padding: 4px;
      font-size: 12px;
    }
    .side_panel {
      width: 360px;
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 8px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .side_actions {
      display: flex;
      gap: 8px;
    }
    .import_panel {
      border: 1px solid #eee;
      border-radius: 6px;
      padding: 8px;
      background: #fafafa;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .import_panel textarea {
      width: 100%;
      min-height: 150px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      padding: 6px;
      border: 1px solid #ddd;
      border-radius: 4px;
    }
    .import_actions {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .status_text {
      font-size: 11px;
      color: #555;
    }
    .category_list {
      overflow: auto;
      border: 1px solid #eee;
      border-radius: 6px;
      background: #fafafa;
      min-height: 150px;
      max-height: 34vh;
    }
    .category_item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 7px;
      border-bottom: 1px solid #eee;
      font-size: 12px;
    }
    .category_item:last-child { border-bottom: none; }
    .category_name { word-break: break-word; }
    button {
      border: 1px solid #ccc;
      background: #fff;
      border-radius: 4px;
      padding: 4px 8px;
      cursor: pointer;
      font-size: 12px;
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    @media (max-width: 980px) {
      .app { flex-direction: column; }
      .side_panel { width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="main_panel">
      <div class="top_row">
        <p class="row_title">Arrange Bins</p>
        <span class="badge hidden" id="dirty_badge">UNSAVED</span>
      </div>
      <p class="subtle">Layers are vertical. Sections are horizontal.</p>
      <div id="layers"></div>
    </div>

    <div class="side_panel">
      <p class="row_title">Actions</p>
      <div class="side_actions">
        <button id="clear_all_btn">Clear All</button>
        <button id="apply_changes_btn">Apply Changes</button>
      </div>

      <div class="import_panel">
        <p class="row_title" style="font-size:13px;">View Layout JSON</p>
        <textarea id="layout_json_input" placeholder='Paste JSON with "bin_categories"'></textarea>
        <div class="import_actions">
          <button id="view_json_btn">View JSON Layout</button>
          <span class="status_text" id="import_status"></span>
        </div>
      </div>

      <p class="row_title">Unassigned Categories</p>
      <p class="subtle" id="selection_status">Select a bin to assign from this list.</p>
      <div class="category_list" id="category_list"></div>
    </div>
  </div>

  <script>
    let app_state = null;
    let selected_bin = null;

    function allAssignedCategoryIds() {
      const ids = new Set();
      for (const layer of app_state.layers) {
        for (const section of layer.sections) {
          for (const bin of section.bins) {
            for (const category_id of bin.category_ids) ids.add(category_id);
          }
        }
      }
      return ids;
    }

    function unassignedCategories() {
      const assigned = allAssignedCategoryIds();
      return app_state.category_options.filter(c => !assigned.has(c.id));
    }

    function categoryDisplayName(category_id) {
      const known = app_state.category_by_id[category_id];
      return known ? known.name : category_id;
    }

    function categoryListDisplay(category_ids) {
      if (!category_ids || category_ids.length === 0) return 'unassigned';
      return category_ids.map(categoryDisplayName).join(', ');
    }

    function setImportStatus(message, is_error) {
      const status = document.getElementById('import_status');
      status.textContent = message || '';
      status.style.color = is_error ? '#b10f2e' : '#555';
    }

    function renderDirtyBadge() {
      const badge = document.getElementById('dirty_badge');
      if (app_state.is_dirty) {
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }

    async function loadState() {
      const res = await fetch('/api/state');
      app_state = await res.json();
      renderAll();
    }

    function getBin(layer_idx, section_idx, bin_idx) {
      return app_state.layers[layer_idx].sections[section_idx].bins[bin_idx];
    }

    async function assignCategoryList(layer_idx, section_idx, bin_idx, category_ids) {
      const res = await fetch('/api/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layer_idx, section_idx, bin_idx, category_ids }),
      });
      if (!res.ok) {
        const msg = await res.text();
        alert(msg || 'assign failed');
        return;
      }
      app_state = await res.json();
      renderAll();
    }

    async function clearAllBins() {
      const okay = confirm('Set all bins to unassigned in draft?');
      if (!okay) return;
      const res = await fetch('/api/clear_all', { method: 'POST' });
      if (!res.ok) {
        const msg = await res.text();
        alert(msg || 'clear all failed');
        return;
      }
      selected_bin = null;
      app_state = await res.json();
      renderAll();
    }

    async function applyChanges() {
      const okay = confirm('Apply current draft to the local database?');
      if (!okay) return;
      const res = await fetch('/api/apply_changes', { method: 'POST' });
      if (!res.ok) {
        const msg = await res.text();
        alert(msg || 'apply failed');
        return;
      }
      app_state = await res.json();
      setImportStatus('Applied changes to the local database', false);
      renderAll();
    }

    async function viewLayoutJson() {
      const layout_json_text = document.getElementById('layout_json_input').value;
      const res = await fetch('/api/view_layout_json', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout_json_text }),
      });
      if (!res.ok) {
        const msg = await res.text();
        setImportStatus(msg || 'invalid json', true);
        return;
      }
      app_state = await res.json();
      setImportStatus('Preview loaded (unsaved)', false);
      renderAll();
    }

    function selectBin(layer_idx, section_idx, bin_idx) {
      selected_bin = { layer_idx, section_idx, bin_idx };
      renderAll();
    }

    function renderLayers() {
      const root = document.getElementById('layers');
      root.innerHTML = '';

      app_state.layers.forEach((layer, layer_idx) => {
        const layer_el = document.createElement('div');
        layer_el.className = 'layer';

        const header_el = document.createElement('div');
        header_el.className = 'layer_header';
        header_el.textContent = `Layer ${layer_idx}`;
        layer_el.appendChild(header_el);

        const sections_row = document.createElement('div');
        sections_row.className = 'sections_row';

        layer.sections.forEach((section, section_idx) => {
          const section_el = document.createElement('div');
          section_el.className = 'section';

          const title_el = document.createElement('div');
          title_el.className = 'section_title';
          title_el.textContent = `Section ${section_idx}`;
          section_el.appendChild(title_el);

          section.bins.forEach((bin, bin_idx) => {
            const bin_el = document.createElement('div');
            bin_el.className = 'bin';
            const is_selected = selected_bin &&
              selected_bin.layer_idx === layer_idx &&
              selected_bin.section_idx === section_idx &&
              selected_bin.bin_idx === bin_idx;
            if (is_selected) bin_el.classList.add('selected');
            bin_el.addEventListener('click', () => selectBin(layer_idx, section_idx, bin_idx));

            const label_el = document.createElement('div');
            label_el.className = 'bin_label';
            label_el.textContent = `Bin ${bin_idx} (${bin.size})`;
            bin_el.appendChild(label_el);

            const current_el = document.createElement('div');
            current_el.className = 'bin_current';
            current_el.textContent = `Current: ${categoryListDisplay(bin.category_ids)}`;
            bin_el.appendChild(current_el);

            const controls_el = document.createElement('div');
            controls_el.className = 'bin_controls';

            const select_el = document.createElement('select');
            select_el.multiple = true;
            select_el.size = 5;

            app_state.category_options.forEach((cat) => {
              const opt = document.createElement('option');
              opt.value = cat.id;
              opt.textContent = `${cat.name} (${cat.id})`;
              if (bin.category_ids.includes(cat.id)) opt.selected = true;
              select_el.appendChild(opt);
            });

            select_el.addEventListener('change', (event) => {
              const selected_values = Array.from(event.target.selectedOptions).map((opt) => opt.value);
              assignCategoryList(layer_idx, section_idx, bin_idx, selected_values);
            });
            select_el.addEventListener('click', (e) => e.stopPropagation());

            const clear_btn = document.createElement('button');
            clear_btn.textContent = 'x';
            clear_btn.title = 'Set unassigned (no categories)';
            clear_btn.addEventListener('click', (e) => {
              e.stopPropagation();
              assignCategoryList(layer_idx, section_idx, bin_idx, []);
            });

            controls_el.appendChild(select_el);
            controls_el.appendChild(clear_btn);
            bin_el.appendChild(controls_el);
            section_el.appendChild(bin_el);
          });

          sections_row.appendChild(section_el);
        });

        layer_el.appendChild(sections_row);
        root.appendChild(layer_el);
      });
    }

    function renderUnassignedPanel() {
      const selection_status = document.getElementById('selection_status');
      if (selected_bin) {
        selection_status.textContent =
          `Selected: layer ${selected_bin.layer_idx}, section ${selected_bin.section_idx}, bin ${selected_bin.bin_idx}`;
      } else {
        selection_status.textContent = 'Select a bin to assign from this list.';
      }

      const list = document.getElementById('category_list');
      list.innerHTML = '';

      const unassigned = unassignedCategories();
      if (unassigned.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'category_item';
        empty.textContent = 'All categories are currently assigned to at least one bin.';
        list.appendChild(empty);
        return;
      }

      unassigned.forEach((cat) => {
        const row = document.createElement('div');
        row.className = 'category_item';

        const text = document.createElement('div');
        text.className = 'category_name';
        text.textContent = `${cat.name} (${cat.id})`;

        const btn = document.createElement('button');
        btn.textContent = 'Assign';
        btn.disabled = !selected_bin;
        btn.addEventListener('click', () => {
          if (!selected_bin) return;
          const bin = getBin(selected_bin.layer_idx, selected_bin.section_idx, selected_bin.bin_idx);
          if (bin.category_ids.includes(cat.id)) return;
          assignCategoryList(
            selected_bin.layer_idx,
            selected_bin.section_idx,
            selected_bin.bin_idx,
            [...bin.category_ids, cat.id]
          );
        });

        row.appendChild(text);
        row.appendChild(btn);
        list.appendChild(row);
      });
    }

    function renderAll() {
      renderDirtyBadge();
      renderLayers();
      renderUnassignedPanel();
      document.getElementById('apply_changes_btn').disabled = !app_state.is_dirty;
    }

    document.getElementById('clear_all_btn').addEventListener('click', clearAllBins);
    document.getElementById('apply_changes_btn').addEventListener('click', applyChanges);
    document.getElementById('view_json_btn').addEventListener('click', viewLayoutJson);
    loadState();
  </script>
</body>
</html>
"""


app = Flask(__name__)
state_lock = threading.Lock()
app_state: dict = {}


def cloneData(data):
    return json.loads(json.dumps(data))


def getBinLayoutConfigFromMain(gc) -> BinLayoutConfig:
    machine_config = loadMachineConfig(gc)
    if machine_config.layer_sections:
        return BinLayoutConfig(
            layers=[LayerConfig(sections=sections) for sections in machine_config.layer_sections]
        )
    return DEFAULT_BIN_LAYOUT


def loadSortingCategoriesFromMain(gc) -> list[dict[str, str]]:
    with open(gc.sorting_profile_path, "r") as f:
        sorting_profile_data = json.load(f)

    categories_dict = sorting_profile_data.get("categories", {})
    category_options: list[dict[str, str]] = []
    for category_id, category_data in categories_dict.items():
        category_name = str(category_data.get("name", category_id))
        category_options.append({"id": str(category_id), "name": category_name})

    default_category_id = str(sorting_profile_data.get("default_category_id", "misc"))
    if all(c["id"] != default_category_id for c in category_options):
        category_options.append({"id": default_category_id, "name": default_category_id})

    category_options.sort(key=lambda c: c["name"].lower())
    return category_options


def extractCategoryMatrixFromLayers(layers: list[dict]) -> list[list[list[list[str]]]]:
    categories: list[list[list[list[str]]]] = []
    for layer in layers:
        layer_categories: list[list[list[str]]] = []
        for section in layer["sections"]:
            section_categories = [list(b["category_ids"]) for b in section["bins"]]
            layer_categories.append(section_categories)
        categories.append(layer_categories)
    return categories


def validateBinIndex(state: dict, layer_idx: int, section_idx: int, bin_idx: int) -> bool:
    if layer_idx < 0 or section_idx < 0 or bin_idx < 0:
        return False
    if layer_idx >= len(state["layers"]):
        return False
    if section_idx >= len(state["layers"][layer_idx]["sections"]):
        return False
    if bin_idx >= len(state["layers"][layer_idx]["sections"][section_idx]["bins"]):
        return False
    return True


def buildCategoryOptionsForState(state: dict) -> list[dict[str, str]]:
    known_by_id = {c["id"]: c["name"] for c in state["base_category_options"]}
    draft_ids = set()
    for layer in state["layers"]:
        for section in layer["sections"]:
            for b in section["bins"]:
                for category_id in b["category_ids"]:
                    draft_ids.add(category_id)

    for category_id in draft_ids:
        if category_id not in known_by_id:
            known_by_id[category_id] = category_id

    merged = [{"id": category_id, "name": name} for category_id, name in known_by_id.items()]
    merged.sort(key=lambda c: c["name"].lower())
    return merged


def refreshDerivedState(state: dict) -> None:
    state["category_options"] = buildCategoryOptionsForState(state)
    state["category_by_id"] = {c["id"]: {"name": c["name"]} for c in state["category_options"]}
    draft_matrix = extractCategoryMatrixFromLayers(state["layers"])
    state["is_dirty"] = draft_matrix != state["saved_categories"]


def buildLayersFromLayout(layout) -> list[dict]:
    layers = []
    for layer in layout.layers:
        layer_data = {"sections": []}
        for section in layer.sections:
            section_data = {"bins": []}
            for b in section.bins:
                section_data["bins"].append({"size": b.size.value, "category_ids": list(b.category_ids)})
            layer_data["sections"].append(section_data)
        layers.append(layer_data)
    return layers


def applyCategoryMatrixToLayers(layers: list[dict], category_matrix: list[list[list[list[str]]]]) -> None:
    for layer_idx, layer in enumerate(layers):
        for section_idx, section in enumerate(layer["sections"]):
            for bin_idx, b in enumerate(section["bins"]):
                b["category_ids"] = list(category_matrix[layer_idx][section_idx][bin_idx])


def parseIncomingCategoryMatrix(raw_text: str) -> list[list[list[list[str]]]]:
    try:
        payload = json.loads(raw_text)
    except Exception as e:
        raise ValueError(f"invalid json: {e}")

    if isinstance(payload, dict) and "bin_categories" in payload:
        payload = payload["bin_categories"]

    if not isinstance(payload, list):
        raise ValueError("json must be a list or contain bin_categories")

    matrix: list[list[list[list[str]]]] = []
    for layer in payload:
        if not isinstance(layer, list):
            raise ValueError("each layer must be a list")
        parsed_layer = []
        for section in layer:
            if not isinstance(section, list):
                raise ValueError("each section must be a list")
            parsed_section = []
            for category_ids in section:
                if not isinstance(category_ids, list):
                    raise ValueError("each bin must be a list of strings")
                parsed_bin_categories = []
                for category_id in category_ids:
                    if not isinstance(category_id, str):
                        raise ValueError("category values must be strings")
                    parsed_bin_categories.append(category_id)
                parsed_section.append(parsed_bin_categories)
            parsed_layer.append(parsed_section)
        matrix.append(parsed_layer)

    return matrix


def categoryMatrixMatchesLayers(layers: list[dict], category_matrix: list[list[list[list[str]]]]) -> bool:
    if len(category_matrix) != len(layers):
        return False
    for layer_idx, layer in enumerate(layers):
        sections = layer["sections"]
        if len(category_matrix[layer_idx]) != len(sections):
            return False
        for section_idx, section in enumerate(sections):
            bins = section["bins"]
            if len(category_matrix[layer_idx][section_idx]) != len(bins):
                return False
    return True


def buildStateFromMain() -> dict:
    gc = mkGlobalConfig()
    bin_layout_config = getBinLayoutConfigFromMain(gc)
    layout = mkLayoutFromConfig(bin_layout_config)

    saved_categories = getBinCategories()
    if saved_categories is not None and layoutMatchesCategories(layout, saved_categories):
        applyCategories(layout, saved_categories)

    layers = buildLayersFromLayout(layout)
    saved_matrix = extractCategoryMatrixFromLayers(layers)

    base_category_options = loadSortingCategoriesFromMain(gc)

    state = {
        "layers": layers,
        "saved_categories": cloneData(saved_matrix),
        "base_category_options": base_category_options,
    }
    refreshDerivedState(state)
    return state


def stateForClient(state: dict) -> dict:
    return {
        "layers": state["layers"],
        "category_options": state["category_options"],
        "category_by_id": state["category_by_id"],
        "is_dirty": state["is_dirty"],
    }


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/api/state")
def getState():
    with state_lock:
        return jsonify(stateForClient(app_state))


@app.post("/api/assign")
def assignCategory():
    payload = request.get_json(silent=True) or {}

    layer_idx = payload.get("layer_idx")
    section_idx = payload.get("section_idx")
    bin_idx = payload.get("bin_idx")
    category_ids = payload.get("category_ids")

    if not isinstance(layer_idx, int) or not isinstance(section_idx, int) or not isinstance(bin_idx, int):
        return ("invalid bin indexes", 400)
    if not isinstance(category_ids, list) or any(not isinstance(category_id, str) for category_id in category_ids):
        return ("invalid category_ids", 400)

    with state_lock:
        if not validateBinIndex(app_state, layer_idx, section_idx, bin_idx):
            return ("bin index out of range", 400)

        app_state["layers"][layer_idx]["sections"][section_idx]["bins"][bin_idx]["category_ids"] = list(dict.fromkeys(category_ids))
        refreshDerivedState(app_state)
        return jsonify(stateForClient(app_state))


@app.post("/api/clear_all")
def clearAllBins():
    with state_lock:
        for layer in app_state["layers"]:
            for section in layer["sections"]:
                for b in section["bins"]:
                    b["category_ids"] = []
        refreshDerivedState(app_state)
        return jsonify(stateForClient(app_state))


@app.post("/api/view_layout_json")
def viewLayoutJson():
    payload = request.get_json(silent=True) or {}
    layout_json_text = payload.get("layout_json_text")

    if not isinstance(layout_json_text, str) or not layout_json_text.strip():
        return ("layout_json_text is required", 400)

    try:
        category_matrix = parseIncomingCategoryMatrix(layout_json_text)
    except ValueError as e:
        return (str(e), 400)

    with state_lock:
        if not categoryMatrixMatchesLayers(app_state["layers"], category_matrix):
            return ("bin_categories shape does not match current layout", 400)

        applyCategoryMatrixToLayers(app_state["layers"], category_matrix)
        refreshDerivedState(app_state)
        return jsonify(stateForClient(app_state))


@app.post("/api/apply_changes")
def applyChanges():
    with state_lock:
        draft_matrix = extractCategoryMatrixFromLayers(app_state["layers"])
        setBinCategories(draft_matrix)
        app_state["saved_categories"] = cloneData(draft_matrix)
        refreshDerivedState(app_state)
        return jsonify(stateForClient(app_state))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    global app_state
    with state_lock:
        app_state = buildStateFromMain()

    print(f"arrange_bins on http://localhost:{DEFAULT_PORT}")
    app.run(
        host="0.0.0.0",
        port=DEFAULT_PORT,
        debug=args.reload,
        use_reloader=args.reload,
    )


if __name__ == "__main__":
    main()
