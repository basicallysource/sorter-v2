"""Run planning: which profile rules take which bins, by layer role.

A run is planned against the bin layout's layer roles. The operator picks the
primary rules (set targets) that take part; those go to primary-role bins in
rule order, secondary rules (side sorting) go to secondary-role bins in rule
order, and every other rule stays unassigned so its pieces pass through to the
bottom tray. Only enabled layers and sections count as capacity.
"""

from __future__ import annotations

from typing import Any

from irl.bin_layout import BinLayoutConfig, LAYER_ROLES
from sorting_profile import ruleRole

Categories = list[list[list[list[str]]]]


def activeRules(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rules = artifact.get("rules") if isinstance(artifact, dict) else None
    if not isinstance(rules, list):
        return []
    return [
        rule
        for rule in rules
        if isinstance(rule, dict) and not rule.get("disabled") and isinstance(rule.get("id"), str) and rule["id"]
    ]


def rulesByRole(rules: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {role: [] for role in LAYER_ROLES}
    for rule in rules:
        grouped[ruleRole(rule)].append(rule)
    return grouped


def roleCapacity(config: BinLayoutConfig) -> dict[str, int]:
    """Usable bins per layer role (enabled layers and sections only)."""
    capacity = {role: 0 for role in LAYER_ROLES}
    for layer in config.layers:
        if not layer.enabled:
            continue
        for section, section_on in zip(layer.sections, layer.section_enabled or []):
            if section_on:
                capacity[layer.role] += len(section)
    return capacity


def defaultPrimarySelection(rules: list[dict[str, Any]], config: BinLayoutConfig) -> list[str]:
    """The first N primary rules, N = primary capacity."""
    primary = rulesByRole(rules)["primary"]
    return [rule["id"] for rule in primary[: roleCapacity(config)["primary"]]]


def planCategories(
    config: BinLayoutConfig,
    rules: list[dict[str, Any]],
    selected_primary_ids: list[str],
) -> Categories:
    """Bin categories for a run: one rule id per bin, filled by role in rule
    order; every other bin is left empty. Layout shape follows ``config``."""
    selected = set(selected_primary_ids)
    grouped = rulesByRole(rules)
    queues = {
        "primary": [rule["id"] for rule in grouped["primary"] if rule["id"] in selected],
        "secondary": [rule["id"] for rule in grouped["secondary"]],
    }
    # A layout with bins of only one role has nothing to separate: the other
    # role's rules queue up behind that role's own rules instead of losing
    # their bins (a filter-only profile on an all-primary tower still sorts).
    capacity = roleCapacity(config)
    for role, other in (("secondary", "primary"), ("primary", "secondary")):
        if capacity[role] == 0 and capacity[other] > 0:
            queues[other] += queues[role]
            queues[role] = []
    categories: Categories = []
    for layer in config.layers:
        queue = queues[layer.role]
        layer_out = []
        for section, section_on in zip(layer.sections, layer.section_enabled or []):
            usable = layer.enabled and section_on
            layer_out.append([[queue.pop(0)] if usable and queue else [] for _ in section])
        categories.append(layer_out)
    return categories


def binAddresses(categories: Categories) -> dict[str, dict[str, int]]:
    """rule id -> first bin holding it."""
    addresses: dict[str, dict[str, int]] = {}
    for layer_index, layer in enumerate(categories):
        for section_index, section in enumerate(layer):
            for bin_index, category_ids in enumerate(section):
                for category_id in category_ids:
                    addresses.setdefault(
                        category_id,
                        {"layer_index": layer_index, "section_index": section_index, "bin_index": bin_index},
                    )
    return addresses
