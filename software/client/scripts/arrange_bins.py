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
    .side_panel {
      width: 320px;
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 8px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .row_title {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }
    .subtle {
      color: #666;
      font-size: 12px;
    }
    .layer {
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 8px;
      margin-bottom: 10px;
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
    .bin select {
      width: 100%;
      padding: 4px;
      font-size: 12px;
    }
    .bin_controls {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .bin_controls select {
      flex: 1;
    }
    .clear_btn {
      padding: 4px 8px;
      border: 1px solid #ccc;
      border-radius: 4px;
      background: #fff;
      font-size: 12px;
      line-height: 1;
      cursor: pointer;
    }
    .category_list {
      overflow: auto;
      border: 1px solid #eee;
      border-radius: 6px;
      background: #fafafa;
      min-height: 150px;
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
      <p class="row_title">Arrange Bins</p>
      <p class="subtle">Layers are vertical. Sections are horizontal.</p>
      <div id="layers"></div>
    </div>
    <div class="side_panel">
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
            if (bin.category_id !== null) ids.add(bin.category_id);
          }
        }
      }
      return ids;
    }

    function unassignedCategories() {
      const assigned = allAssignedCategoryIds();
      return app_state.category_options.filter(c => !assigned.has(c.id));
    }

    async function loadState() {
      const res = await fetch('/api/state');
      app_state = await res.json();
      renderAll();
    }

    async function assignCategory(layer_idx, section_idx, bin_idx, category_id) {
      const res = await fetch('/api/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layer_idx, section_idx, bin_idx, category_id }),
      });
      if (!res.ok) {
        const msg = await res.text();
        alert(msg || 'assign failed');
        return;
      }
      app_state = await res.json();
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

            const select_el = document.createElement('select');

            const empty_opt = document.createElement('option');
            empty_opt.value = '';
            empty_opt.textContent = 'unassigned';
            if (bin.category_id === null) empty_opt.selected = true;
            select_el.appendChild(empty_opt);

            app_state.category_options.forEach((cat) => {
              const opt = document.createElement('option');
              opt.value = cat.id;
              opt.textContent = `${cat.name} (${cat.id})`;
              if (bin.category_id === cat.id) opt.selected = true;
              select_el.appendChild(opt);
            });

            select_el.addEventListener('change', (e) => {
              const value = e.target.value || null;
              assignCategory(layer_idx, section_idx, bin_idx, value);
            });
            select_el.addEventListener('click', (e) => e.stopPropagation());

            const controls_el = document.createElement('div');
            controls_el.className = 'bin_controls';

            const clear_btn = document.createElement('button');
            clear_btn.className = 'clear_btn';
            clear_btn.textContent = 'x';
            clear_btn.title = 'Set unassigned';
            clear_btn.addEventListener('click', (e) => {
              e.stopPropagation();
              assignCategory(layer_idx, section_idx, bin_idx, null);
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
          assignCategory(selected_bin.layer_idx, selected_bin.section_idx, selected_bin.bin_idx, cat.id);
        });

        row.appendChild(text);
        row.appendChild(btn);
        list.appendChild(row);
      });
    }

    function renderAll() {
      renderLayers();
      renderUnassignedPanel();
    }

    loadState();
  </script>
</body>
</html>
"""


app = Flask(__name__)
state_lock = threading.Lock()
app_state: dict = {}


def getBinLayoutConfigFromMain(gc) -> BinLayoutConfig:
    machine_config = loadMachineConfig(gc)
    if machine_config.layer_sections:
        return BinLayoutConfig(
            layers=[
                LayerConfig(sections=sections) for sections in machine_config.layer_sections
            ]
        )
    return DEFAULT_BIN_LAYOUT


def loadSortingCategoriesFromMain(gc) -> list[dict[str, str]]:
    with open(gc.sorting_profile_path, "r") as f:
        sorting_profile_data = json.load(f)

    categories_dict = sorting_profile_data.get("categories", {})
    category_options = []
    for category_id, category_data in categories_dict.items():
        category_name = str(category_data.get("name", category_id))
        category_options.append({"id": str(category_id), "name": category_name})

    default_category_id = str(sorting_profile_data.get("default_category_id", "misc"))
    has_default = any(c["id"] == default_category_id for c in category_options)
    if not has_default:
        category_options.append({"id": default_category_id, "name": default_category_id})

    category_options.sort(key=lambda c: c["name"].lower())
    return category_options


def buildStateFromMain() -> dict:
    gc = mkGlobalConfig()
    bin_layout_config = getBinLayoutConfigFromMain(gc)
    layout = mkLayoutFromConfig(bin_layout_config)

    saved_categories = getBinCategories()
    if saved_categories is not None and layoutMatchesCategories(layout, saved_categories):
        applyCategories(layout, saved_categories)

    layers = []
    for layer in layout.layers:
        layer_data = {"sections": []}
        for section in layer.sections:
            section_data = {"bins": []}
            for b in section.bins:
                section_data["bins"].append(
                    {
                        "size": b.size.value,
                        "category_id": b.category_id,
                    }
                )
            layer_data["sections"].append(section_data)
        layers.append(layer_data)

    category_options = loadSortingCategoriesFromMain(gc)
    category_by_id = {c["id"]: {"name": c["name"]} for c in category_options}

    return {
        "layers": layers,
        "category_options": category_options,
        "category_by_id": category_by_id,
    }


def extractCategoryMatrix(state: dict) -> list[list[list[str | None]]]:
    categories: list[list[list[str | None]]] = []
    for layer in state["layers"]:
        layer_categories = []
        for section in layer["sections"]:
            section_categories = [b["category_id"] for b in section["bins"]]
            layer_categories.append(section_categories)
        categories.append(layer_categories)
    return categories


def validateCategoryChoice(state: dict, category_id: str | None) -> bool:
    if category_id is None:
        return True
    return category_id in state["category_by_id"]


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


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/api/state")
def getState():
    with state_lock:
        return jsonify(app_state)


@app.post("/api/assign")
def assignCategory():
    payload = request.get_json(silent=True) or {}

    layer_idx = payload.get("layer_idx")
    section_idx = payload.get("section_idx")
    bin_idx = payload.get("bin_idx")
    category_id = payload.get("category_id")

    if not isinstance(layer_idx, int) or not isinstance(section_idx, int) or not isinstance(bin_idx, int):
        return ("invalid bin indexes", 400)
    if category_id is not None and not isinstance(category_id, str):
        return ("invalid category_id", 400)

    with state_lock:
        if not validateBinIndex(app_state, layer_idx, section_idx, bin_idx):
            return ("bin index out of range", 400)
        if not validateCategoryChoice(app_state, category_id):
            return ("unknown category_id", 400)

        app_state["layers"][layer_idx]["sections"][section_idx]["bins"][bin_idx]["category_id"] = category_id
        setBinCategories(extractCategoryMatrix(app_state))
        return jsonify(app_state)


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
