import re
import uuid


def mkCondition(field, op, value):
    return {"id": str(uuid.uuid4()), "field": field, "op": op, "value": value}


# --- predicate evaluation ---

def _evalPredicate(cond, part, color_id, ctx=None):
    field = cond["field"]
    op = cond["op"]
    value = cond["value"]
    actual = _getFieldValue(field, part, color_id, ctx)

    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "in":
        return actual in value
    if op == "contains":
        return isinstance(actual, str) and value.lower() in actual.lower()
    if op == "regex":
        return isinstance(actual, str) and bool(re.search(value, actual, re.IGNORECASE))
    if op == "gte":
        return actual is not None and actual >= value
    if op == "lte":
        return actual is not None and actual <= value
    return False


def _toFloat(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _getBricklinkPrimaryItem(part):
    bricklink_data = part.get("bricklink_data")
    if not isinstance(bricklink_data, dict):
        return None
    items = bricklink_data.get("items")
    if not isinstance(items, dict) or not items:
        return None
    primary_item_no = bricklink_data.get("primary_item_no")
    if primary_item_no and primary_item_no in items:
        return items[primary_item_no]
    return next(iter(items.values()))


def _getNested(obj, *path):
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _getPriceSection(part, section="ord_used"):
    bl_item = _getBricklinkPrimaryItem(part)
    if not bl_item:
        return None
    pg = bl_item.get("price_guide")
    if not isinstance(pg, dict):
        return None
    return pg.get(section)


def _partPreviewMeta(part, ctx=None):
    empty = {
        "part_img_url": None, "part_cat_id": None, "year_from": None, "year_to": None,
        "bricklink_ids": [], "part_url": None,
        "bl_price_min": None, "bl_price_max": None, "bl_price_avg": None,
        "bl_price_qty_avg": None, "bl_price_lots": None, "bl_price_qty": None,
        "bl_price_section": None, "bl_catalog_name": None, "bl_category_name": None,
    }
    if not part:
        return empty
    # default to ord_used (past 6mo sales, used) — matches BrickStore behavior
    section = _getPriceSection(part, "ord_used") or _getPriceSection(part, "inv_used")
    section_name = "ord_used" if _getPriceSection(part, "ord_used") else "inv_used"
    bl_item = _getBricklinkPrimaryItem(part)
    bl_name = _getNested(bl_item, "catalog", "data", "name")
    bl_cat_id = _getNested(bl_item, "catalog", "data", "category_id")
    bl_cat_name = None
    if bl_cat_id is not None and ctx and "bricklink_categories" in ctx:
        bl_cat = ctx["bricklink_categories"].get(bl_cat_id)
        if isinstance(bl_cat, dict):
            bl_cat_name = bl_cat.get("category_name", "")
    return {
        "part_img_url": part.get("part_img_url"),
        "part_cat_id": part.get("part_cat_id"),
        "year_from": part.get("year_from"),
        "year_to": part.get("year_to"),
        "bricklink_ids": part.get("external_ids", {}).get("BrickLink", []),
        "part_url": part.get("part_url"),
        "bl_price_min": section.get("min") if section else None,
        "bl_price_max": section.get("max") if section else None,
        "bl_price_avg": section.get("avg") if section else None,
        "bl_price_qty_avg": section.get("wavg") if section else None,
        "bl_price_lots": section.get("lots") if section else None,
        "bl_price_qty": section.get("qty") if section else None,
        "bl_price_section": section_name if section else None,
        "bl_catalog_name": bl_name,
        "bl_category_name": bl_cat_name,
    }


def _getFieldValue(field, part, color_id, ctx=None):
    if field == "category_id":
        return part.get("part_cat_id")
    if field == "category_name":
        cat_id = part.get("part_cat_id")
        if ctx and "categories" in ctx:
            cat = ctx["categories"].get(cat_id)
            return cat["name"] if cat else ""
        return ""
    if field == "color_id":
        return color_id
    if field == "name":
        return part.get("name", "")
    if field == "part_num":
        return part.get("part_num", "")
    if field == "year_from":
        return part.get("year_from")
    if field == "year_to":
        return part.get("year_to")
    if field == "bricklink_id":
        bl_ids = part.get("external_ids", {}).get("BrickLink", [])
        return bl_ids[0] if bl_ids else None
    if field == "bricklink_item_count":
        bricklink_data = part.get("bricklink_data")
        items = bricklink_data.get("items") if isinstance(bricklink_data, dict) else None
        return len(items) if isinstance(items, dict) else None
    if field == "bricklink_primary_item_no":
        bricklink_data = part.get("bricklink_data")
        return bricklink_data.get("primary_item_no") if isinstance(bricklink_data, dict) else None

    # backward-compat price fields default to ord_used (past 6mo sales, used)
    section = _getPriceSection(part, "ord_used") or _getPriceSection(part, "inv_used")
    if field == "bl_price_min":
        return section.get("min") if section else None
    if field == "bl_price_max":
        return section.get("max") if section else None
    if field == "bl_price_avg":
        return section.get("avg") if section else None
    if field == "bl_price_qty_avg":
        return section.get("wavg") if section else None
    if field == "bl_price_unit_quantity" or field == "bl_price_lots":
        return section.get("lots") if section else None
    if field == "bl_price_total_quantity" or field == "bl_price_qty":
        return section.get("qty") if section else None

    # section-specific fields: bl_price_{section}_{metric}
    SECTION_MAP = {"inv_new": "inv_new", "inv_used": "inv_used", "ord_new": "ord_new", "ord_used": "ord_used"}
    for sec_key in SECTION_MAP:
        prefix = f"bl_price_{sec_key}_"
        if field.startswith(prefix):
            metric = field[len(prefix):]
            s = _getPriceSection(part, sec_key)
            if not s:
                return None
            return s.get(metric)

    bricklink_item = _getBricklinkPrimaryItem(part)
    if field == "bl_catalog_name":
        return _getNested(bricklink_item, "catalog", "data", "name")
    if field == "bl_catalog_category_id":
        return _getNested(bricklink_item, "catalog", "data", "category_id")
    if field == "bl_category_id":
        return _getNested(bricklink_item, "catalog", "data", "category_id")
    if field == "bl_category_name":
        bl_cat_id = _getNested(bricklink_item, "catalog", "data", "category_id")
        if bl_cat_id is None:
            return ""
        if ctx and "bricklink_categories" in ctx:
            bl_cat = ctx["bricklink_categories"].get(bl_cat_id)
            if isinstance(bl_cat, dict):
                return bl_cat.get("category_name", "")
        return ""
    if field == "bl_catalog_year_released":
        return _getNested(bricklink_item, "catalog", "data", "year_released")
    if field == "bl_catalog_weight":
        return _toFloat(_getNested(bricklink_item, "catalog", "data", "weight"))
    if field == "bl_catalog_dim_x":
        return _toFloat(_getNested(bricklink_item, "catalog", "data", "dim_x"))
    if field == "bl_catalog_dim_y":
        return _toFloat(_getNested(bricklink_item, "catalog", "data", "dim_y"))
    if field == "bl_catalog_dim_z":
        return _toFloat(_getNested(bricklink_item, "catalog", "data", "dim_z"))
    if field == "bl_catalog_is_obsolete":
        val = _getNested(bricklink_item, "catalog", "data", "is_obsolete")
        if val is None:
            return None
        return 1 if val else 0
    return None


# --- rule evaluation ---

def _evaluateRuleConditions(conditions, match_mode, part, color_id, ctx=None, children=None):
    # each direct condition is a boolean, each child is a compound boolean
    results = []
    for c in (conditions or []):
        results.append(_evalPredicate(c, part, color_id, ctx))
    for child in (children or []):
        if child.get("disabled"):
            continue
        child_children = [c for c in child.get("children", []) if not c.get("disabled")]
        child_result = _evaluateRuleConditions(
            child.get("conditions", []), child.get("match_mode", "all"),
            part, color_id, ctx, child_children,
        )
        results.append(child_result)
    if not results:
        return True
    fn = all if match_mode == "all" else any
    return fn(results)


def _collectAllConditions(rule):
    conds = list(rule.get("conditions", []))
    for child in rule.get("children", []):
        if not child.get("disabled"):
            conds.extend(_collectAllConditions(child))
    return conds


def _ruleHasColorConditions(conditions):
    return any(c.get("field") == "color_id" for c in conditions)


def _extractColorValues(conditions):
    colors = set()
    for c in conditions:
        if c.get("field") == "color_id":
            if c["op"] == "eq":
                colors.add(c["value"])
            elif c["op"] == "in":
                colors.update(c["value"])
    return colors


def _allConditions(checks):
    conds = []
    for check in checks:
        conds.extend(check["conditions"])
        for child in check.get("children", []):
            if not child.get("disabled"):
                conds.extend(_collectAllConditions(child))
    return conds


def _evaluateChecks(checks, part, color_id, ctx=None):
    for check in checks:
        if not _evaluateRuleConditions(
            check["conditions"], check["match_mode"],
            part, color_id, ctx, check.get("children"),
        ):
            return False
    return True


def _flattenRules(rules, ancestor_checks=None, top_level_id=None):
    if ancestor_checks is None:
        ancestor_checks = []
    flat = []
    for rule in rules:
        if rule.get("disabled"):
            continue
        tid = top_level_id or rule["id"]
        children = [c for c in rule.get("children", []) if not c.get("disabled")]
        own_check = {
            "conditions": rule.get("conditions", []),
            "match_mode": rule.get("match_mode", "all"),
            "children": children,
        }
        checks = ancestor_checks + [own_check]
        flat.append({"rule": rule, "top_level_id": tid, "checks": checks})
        # children are evaluated inline as compound conditions, not separate entries
    return flat


def _partKey(part, color_id):
    bl_ids = part.get("external_ids", {}).get("BrickLink", [])
    part_id = bl_ids[0] if bl_ids else part.get("part_num", "")
    if color_id is not None:
        return f"{color_id}-{part_id}"
    return f"any_color-{part_id}"


def generateProfile(sp, parts, categories=None, bricklink_categories=None, fallback_mode=None):
    ctx = {}
    if categories:
        ctx["categories"] = categories
    if bricklink_categories:
        ctx["bricklink_categories"] = bricklink_categories
    if not ctx:
        ctx = None
    fb = fallback_mode or getattr(sp, "fallback_mode", None) or {}
    use_rb_cats = fb.get("rebrickable_categories", False)
    use_by_color = fb.get("by_color", False)

    flat = []
    for rule in sp.rules:
        flat.extend(_flattenRules([rule]))
    part_to_category = {}
    stats = {"total_parts": len(parts), "matched": 0, "unmatched": 0, "per_category": {}}

    for _pnum, part in parts.items():
        matched = False
        for entry in flat:
            all_conds = _allConditions(entry["checks"])
            if not all_conds:
                continue
            color_sensitive = _ruleHasColorConditions(all_conds)

            if color_sensitive:
                rule_colors = _extractColorValues(all_conds)
                for cid in rule_colors:
                    if _evaluateChecks(entry["checks"], part, cid, ctx):
                        key = _partKey(part, cid)
                        if key not in part_to_category:
                            part_to_category[key] = entry["top_level_id"]
                            matched = True
            else:
                if _evaluateChecks(entry["checks"], part, None, ctx):
                    key = _partKey(part, None)
                    if key not in part_to_category:
                        part_to_category[key] = entry["top_level_id"]
                        matched = True
            if matched:
                break

        if not matched:
            if use_rb_cats:
                cat_id = part.get("part_cat_id")
                fallback_cat = f"rb_{cat_id}" if cat_id is not None else sp.default_category_id
                key = _partKey(part, None)
                if key not in part_to_category:
                    part_to_category[key] = fallback_cat
                    stats["unmatched"] += 1
            elif sp.default_category_id:
                key = _partKey(part, None)
                if key not in part_to_category:
                    part_to_category[key] = sp.default_category_id
                    stats["unmatched"] += 1

        if matched:
            stats["matched"] += 1

    for key, cat_id in part_to_category.items():
        stats["per_category"][cat_id] = stats["per_category"].get(cat_id, 0) + 1

    return {"part_to_category": part_to_category, "stats": stats}


def partsForCategory(part_to_category, cat_id, parts, q="", offset=0, limit=50, categories=None, bricklink_categories=None):
    ctx = {}
    if categories:
        ctx["categories"] = categories
    if bricklink_categories:
        ctx["bricklink_categories"] = bricklink_categories
    if not ctx:
        ctx = None
    all_matches = []
    seen_keys = set()
    bl_to_rb = None
    q_lower = q.strip().lower()

    def resolvePart(stored_part_num):
        nonlocal bl_to_rb
        part = parts.get(stored_part_num)
        if part:
            return part, stored_part_num
        if bl_to_rb is None:
            bl_to_rb = {}
            for rb_part_num, rb_part in parts.items():
                for bl_id in rb_part.get("external_ids", {}).get("BrickLink", []):
                    bl_to_rb[str(bl_id)] = rb_part_num
        rb_part_num = bl_to_rb.get(str(stored_part_num))
        if rb_part_num:
            return parts.get(rb_part_num), rb_part_num
        return None, stored_part_num

    for key, cid in part_to_category.items():
        if cid != cat_id:
            continue
        sep = key.index('-')
        color_part = key[:sep]
        stored_part_num = key[sep + 1:]
        color_id = None if color_part == "any_color" else color_part
        part, display_part_num = resolvePart(stored_part_num)
        name = part.get("name", "") if part else ""
        if q_lower and q_lower not in name.lower() and q_lower not in display_part_num.lower() and q_lower not in stored_part_num.lower():
            continue
        dedupe_key = (color_id, display_part_num)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        entry = {"part_num": display_part_num, "name": name}
        entry.update(_partPreviewMeta(part, ctx))
        if color_id is not None:
            entry["color_id"] = color_id
        all_matches.append(entry)
    total = len(all_matches)
    page = all_matches[offset:offset + limit] if limit else all_matches
    return {"total": total, "sample": page, "offset": offset, "limit": limit}


def previewRule(rule, parts, categories=None, bricklink_categories=None, limit=50, offset=0, q="", ancestor_checks=None):
    ctx = {}
    if categories:
        ctx["categories"] = categories
    if bricklink_categories:
        ctx["bricklink_categories"] = bricklink_categories
    if not ctx:
        ctx = None
    if ancestor_checks is None:
        ancestor_checks = []
    checks = ancestor_checks + [{"conditions": rule.get("conditions", []), "match_mode": rule.get("match_mode", "all")}]
    all_conds = _allConditions(checks)

    if not all_conds:
        return {"total": 0, "sample": [], "offset": offset, "limit": limit}

    color_sensitive = _ruleHasColorConditions(all_conds)
    q_lower = q.strip().lower()

    matches = []
    for pnum, part in parts.items():
        if color_sensitive:
            rule_colors = _extractColorValues(all_conds)
            for cid in rule_colors:
                if _evaluateChecks(checks, part, cid, ctx):
                    entry = {"part_num": pnum, "name": part.get("name", ""), "color_id": cid}
                    entry.update(_partPreviewMeta(part, ctx))
                    if not q_lower or q_lower in entry["name"].lower() or q_lower in pnum.lower():
                        matches.append(entry)
                    break
        else:
            if _evaluateChecks(checks, part, None, ctx):
                entry = {"part_num": pnum, "name": part.get("name", "")}
                entry.update(_partPreviewMeta(part, ctx))
                if not q_lower or q_lower in entry["name"].lower() or q_lower in pnum.lower():
                    matches.append(entry)

    total = len(matches)
    page = matches[offset:offset + limit] if limit else matches
    return {"total": total, "sample": page, "offset": offset, "limit": limit}
