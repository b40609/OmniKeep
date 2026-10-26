"""Hard Rules Engine for OmniKeep (Karakeep pattern)

Executes deterministic automation rules during ingestion and radar filtering:
- Matches against URL, domain, title, source_type, or content
- Applies tags, category overrides, star/archive flags, or mute signals
- Fast, deterministic, and operates with zero LLM overhead
"""
from typing import Dict, Any, List, Optional
import re
from urllib.parse import urlparse
from app.database import get_all_rules


def _extract_field_value(item: Dict[str, Any], field: str) -> str:
    """Extracts target string representation for rule evaluation."""
    f = field.strip().lower()
    if f == "url":
        return str(item.get("url") or "")
    if f == "domain":
        url = str(item.get("url") or "")
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""
    if f == "title":
        return str(item.get("title_l1") or item.get("title") or "")
    if f == "source_type":
        return str(item.get("source_type") or "").lower()
    if f == "content":
        return f"{item.get('summary_l1') or ''} {item.get('content_raw') or ''}"
    return str(item.get(field) or "")


def _match_condition(actual: str, operator: str, expected: str) -> bool:
    """Evaluates a single condition against extracted actual string."""
    op = operator.strip().lower()
    act = actual.strip().lower()
    exp = expected.strip().lower()

    if op == "contains":
        return exp in act
    if op == "equals":
        return act == exp
    if op == "startswith":
        return act.startswith(exp)
    if op == "endswith":
        return act.endswith(exp)
    if op == "regex":
        try:
            return bool(re.search(expected.strip(), actual, re.IGNORECASE))
        except Exception:
            return False
    return False


def apply_rules_to_item(item: Dict[str, Any], active_rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Applies all active rules in priority order to an incoming item dict.

    Modifies fields (category_name, tech_tags, is_starred, is_read) in place and returns item.
    """
    rules = active_rules if active_rules is not None else get_all_rules(active_only=True)
    if not rules:
        return item

    # Ensure tags is a mutable list
    tags = item.get("tech_tags")
    if not isinstance(tags, list):
        try:
            import json
            tags = json.loads(tags) if tags else []
        except Exception:
            tags = [t.strip() for t in str(tags or "").split(",") if t.strip()]
    item["tech_tags"] = list(tags)

    matched_rule_names = []

    for rule in rules:
        field = rule.get("field", "")
        op = rule.get("operator", "")
        val = rule.get("value", "")
        act_type = rule.get("action_type", "")
        act_val = rule.get("action_value", "")

        actual_str = _extract_field_value(item, field)
        if not _match_condition(actual_str, op, val):
            continue

        matched_rule_names.append(rule.get("name", f"Rule #{rule.get('id')}"))

        # Apply action
        if act_type == "add_tag":
            tag_name = act_val.strip()
            if tag_name and tag_name not in item["tech_tags"]:
                item["tech_tags"].append(tag_name)
        elif act_type == "set_category":
            cat_name = act_val.strip()
            if cat_name:
                item["category_name"] = cat_name
        elif act_type == "star":
            item["is_starred"] = 1
        elif act_type == "archive":
            item["is_read"] = 1
        elif act_type == "mute":
            item["is_read"] = 1
            item["is_muted"] = True

    if matched_rule_names:
        item["_applied_rules"] = matched_rule_names

    return item


def evaluate_rules_for_preview(item: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluates rules and returns which rules fired and what fields would change."""
    import copy
    cloned = copy.deepcopy(item)
    original_category = cloned.get("category_name", "Inbox")
    original_tags = list(cloned.get("tech_tags") or [])
    original_starred = cloned.get("is_starred", 0)
    original_read = cloned.get("is_read", 0)

    result = apply_rules_to_item(cloned)

    changes = {}
    if result.get("category_name") != original_category:
        changes["category_name"] = {"before": original_category, "after": result.get("category_name")}
    if result.get("tech_tags") != original_tags:
        changes["tech_tags"] = {"before": original_tags, "after": result.get("tech_tags")}
    if result.get("is_starred") != original_starred:
        changes["is_starred"] = {"before": original_starred, "after": result.get("is_starred")}
    if result.get("is_read") != original_read:
        changes["is_read"] = {"before": original_read, "after": result.get("is_read")}

    return {
        "matched_rules": result.get("_applied_rules", []),
        "changes": changes,
        "result_item": result
    }
