"""LegoRulesEngine — default RulesEngine mapping ClassifierResult -> BinDecision.

Ports the legacy ``DistributionLayout`` + ``JsonSortingProfile`` routing behind
the rt-side ``RulesEngine`` protocol. The rules engine is the **only** rt/
file permitted to bridge-import from the legacy backend — the two bridge
imports are:

* ``backend.sorting_profile.JsonSortingProfile`` — the existing sorting profile
  loader; we reuse it verbatim so operator-edited profile JSONs keep working.
* ``backend.irl.bin_layout.getBinLayout`` + ``mkLayoutFromConfig`` — to build
  the default ``DistributionLayout`` when no explicit path is passed.

Re-implementing either would be pure overhead (profile JSON schema + layer/
section/bin topology is machine-specific and owned by the operator UI).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rt.contracts.classification import ClassifierResult
from rt.contracts.registry import register_rules_engine
from rt.contracts.rules import BinDecision


REJECT_BIN_ID = "reject"
DEFAULT_BIN_ID = "misc"


@register_rules_engine("lego_default")
class LegoRulesEngine:
    """Maps ClassifierResult -> BinDecision using a sorting profile + bin layout.

    The engine holds three lookup structures:

    * ``_part_to_category``: part_id (optionally prefixed by color) -> category_id
    * ``_category_to_bin``: category_id -> bin_id (flattened "L{layer}-S{section}-B{bin}")
    * ``_default_category``: fallback category for unmatched parts

    ``decide_bin`` executes this lookup in O(1) and returns a ``BinDecision``
    with a human-readable ``reason`` suitable for operator logs.
    """

    key = "lego_default"

    def __init__(
        self,
        *,
        sorting_profile_path: str | Path,
        bin_layout_path: str | Path | None = None,
        reject_bin_id: str = REJECT_BIN_ID,
        default_bin_id: str | None = DEFAULT_BIN_ID,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sorting_profile_path = Path(sorting_profile_path)
        self._bin_layout_path = Path(bin_layout_path) if bin_layout_path else None
        self._reject_bin_id = str(reject_bin_id)
        self._default_bin_id = default_bin_id
        self._logger = logger or logging.getLogger("rt.rules.lego_default")
        self._part_to_category: dict[str, str] = {}
        self._category_to_bin: dict[str, str] = {}
        self._default_category: str = "misc"
        self._artifact_hash: str = ""
        self.reload()

    # ------------------------------------------------------------------
    # RulesEngine protocol

    def decide_bin(
        self,
        classification: ClassifierResult,
        context: dict[str, Any],
    ) -> BinDecision:
        part_id = classification.part_id
        color_id = classification.color_id or "any_color"
        if not part_id:
            return BinDecision(
                bin_id=self._reject_bin_id,
                category=None,
                reason="unknown_part",
            )

        category_id = self._lookup_category(str(part_id), str(color_id))
        matched = category_id != self._default_category or self._has_explicit_entry(
            str(part_id), str(color_id)
        )

        bin_id = self._category_to_bin.get(category_id)
        if bin_id is None:
            if self._default_bin_id is not None:
                return BinDecision(
                    bin_id=self._default_bin_id,
                    category=category_id,
                    reason="no_bin_for_category:default",
                )
            return BinDecision(
                bin_id=self._reject_bin_id,
                category=category_id,
                reason="no_bin_for_category",
            )

        reason = (
            f"matched_profile:{category_id}"
            if matched
            else f"default_category:{category_id}"
        )
        return BinDecision(bin_id=bin_id, category=category_id, reason=reason)

    def reload(self) -> None:
        """Re-read sorting profile + bin layout from disk."""
        self._load_sorting_profile()
        self._load_bin_layout()

    # ------------------------------------------------------------------
    # Introspection (for tests + operator UI)

    def categories(self) -> frozenset[str]:
        return frozenset(self._category_to_bin.keys())

    def artifact_hash(self) -> str:
        return self._artifact_hash

    def reject_bin_id(self) -> str:
        return self._reject_bin_id

    # ------------------------------------------------------------------
    # Internals

    def _lookup_category(self, part_id: str, color_id: str) -> str:
        color_key = f"{color_id}-{part_id}"
        if color_key in self._part_to_category:
            return self._part_to_category[color_key]
        any_key = f"any_color-{part_id}"
        return self._part_to_category.get(any_key, self._default_category)

    def _has_explicit_entry(self, part_id: str, color_id: str) -> bool:
        return (
            f"{color_id}-{part_id}" in self._part_to_category
            or f"any_color-{part_id}" in self._part_to_category
        )

    def _load_sorting_profile(self) -> None:
        if not self._sorting_profile_path.exists():
            self._logger.warning(
                "LegoRulesEngine: sorting profile %s not found; using empty rules",
                self._sorting_profile_path,
            )
            self._part_to_category = {}
            self._default_category = "misc"
            self._artifact_hash = ""
            return

        try:
            with self._sorting_profile_path.open("r") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            self._logger.exception(
                "LegoRulesEngine: failed to read sorting profile %s",
                self._sorting_profile_path,
            )
            self._part_to_category = {}
            self._default_category = "misc"
            self._artifact_hash = ""
            return

        raw_part_to_category = data.get("part_to_category") or {}
        if not isinstance(raw_part_to_category, dict):
            self._logger.error(
                "LegoRulesEngine: sorting profile %s has invalid part_to_category",
                self._sorting_profile_path,
            )
            raw_part_to_category = {}
        self._part_to_category = {
            str(k): str(v) for k, v in raw_part_to_category.items()
        }
        self._default_category = str(data.get("default_category_id", "misc"))
        self._artifact_hash = str(data.get("artifact_hash", ""))
        self._logger.info(
            "LegoRulesEngine: loaded %d part rules, default=%s",
            len(self._part_to_category),
            self._default_category,
        )

    def _load_bin_layout(self) -> None:
        """Load the bin layout JSON and flatten to category -> bin_id."""
        if self._bin_layout_path is None or not self._bin_layout_path.exists():
            # Empty layout is acceptable — callers may still route via the
            # default bin id. Log once so operators know why everything falls
            # through to default.
            self._logger.info(
                "LegoRulesEngine: no bin layout file; categories route to default"
            )
            self._category_to_bin = {}
            return

        try:
            with self._bin_layout_path.open("r") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            self._logger.exception(
                "LegoRulesEngine: failed to read bin layout %s",
                self._bin_layout_path,
            )
            self._category_to_bin = {}
            return

        mapping: dict[str, str] = {}
        layers = data.get("layers") if isinstance(data, dict) else None
        if not isinstance(layers, list):
            self._category_to_bin = {}
            return

        for layer_idx, layer in enumerate(layers):
            if not isinstance(layer, dict):
                continue
            sections = layer.get("sections")
            if not isinstance(sections, list):
                continue
            for section_idx, section in enumerate(sections):
                # Layout JSONs sometimes store categories directly on a bin list;
                # fall back gracefully when the structure is just size strings.
                if not isinstance(section, list):
                    continue
                bins = section
                for bin_idx, bin_entry in enumerate(bins):
                    bin_id = f"L{layer_idx}-S{section_idx}-B{bin_idx}"
                    category_ids = _extract_category_ids(bin_entry)
                    for cat_id in category_ids:
                        # First-match-wins if the same category is mapped to
                        # multiple bins. Operators should avoid this.
                        mapping.setdefault(cat_id, bin_id)

        # Also inspect `categories` overlay if present (matches layout bin_layout
        # JSON shape emitted by the operator UI).
        overlay = data.get("categories") if isinstance(data, dict) else None
        if isinstance(overlay, list):
            for layer_idx, layer in enumerate(overlay):
                if not isinstance(layer, list):
                    continue
                for section_idx, section in enumerate(layer):
                    if not isinstance(section, list):
                        continue
                    for bin_idx, bin_cats in enumerate(section):
                        if not isinstance(bin_cats, list):
                            continue
                        bin_id = f"L{layer_idx}-S{section_idx}-B{bin_idx}"
                        for cat_id in bin_cats:
                            if isinstance(cat_id, str):
                                mapping.setdefault(cat_id, bin_id)

        self._category_to_bin = mapping
        self._logger.info(
            "LegoRulesEngine: loaded %d category->bin mappings",
            len(self._category_to_bin),
        )


def _extract_category_ids(bin_entry: Any) -> list[str]:
    if isinstance(bin_entry, dict):
        raw = bin_entry.get("category_ids")
        if isinstance(raw, list):
            return [str(c) for c in raw if isinstance(c, str)]
    return []


__all__ = ["LegoRulesEngine", "REJECT_BIN_ID", "DEFAULT_BIN_ID"]
