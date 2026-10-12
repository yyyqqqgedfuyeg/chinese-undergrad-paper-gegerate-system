"""Deterministic workflow-only hierarchy flattening; never changes research facts."""
from copy import deepcopy
import json
import re


def normalize_workflow_outline(content):
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"outline_plan"}:
        return content, None
    original = value["outline_plan"]
    if not isinstance(original, list) or not original:
        return content, None
    nodes = deepcopy(original)
    ids = [n.get("section_id", "") for n in nodes]
    if any(not re.fullmatch(r"[1-9]\d*(?:\.[1-9]\d*)*", i) for i in ids):
        return content, None
    if len(set(ids)) != len(ids) or any("." in i and i.rsplit(".", 1)[0] not in ids for i in ids):
        return content, None
    if ids != sorted(ids, key=lambda i: tuple(map(int, i.split(".")))):
        return content, None
    if any(type(n.get("target_words")) is not int for n in nodes):
        return content, None
    deeper = any(i.count(".") > 2 for i in ids)
    mapping = {}
    if deeper:
        rebuilt = []
        for original_node in nodes:
            node = deepcopy(original_node)
            sid = node["section_id"]
            if sid.count(".") < 2:
                rebuilt.append(node)
                continue
            descendants = [n for n in nodes if n["section_id"].startswith(sid + ".")]
            if descendants:
                # Only remove structural containers; never lose text/asset tasks.
                if node["target_words"] != 0 or node.get("planned_assets"):
                    return content, None
                continue
            parent = ".".join(sid.split(".")[:2])
            sequence = 1 + sum(n["section_id"].rsplit(".", 1)[0] == parent for n in rebuilt if n["section_id"].count(".") == 2)
            node["section_id"] = f"{parent}.{sequence}"
            if sid.count(".") > 2:
                containers = [n["title"] for n in nodes if sid.startswith(n["section_id"] + ".") and n["section_id"].count(".") >= 2]
                node["title"] = "：".join([*containers, node["title"]])
            mapping[sid] = node["section_id"]
            rebuilt.append(node)
        nodes = rebuilt
    before_words = sum(n["target_words"] for n in nodes)
    if before_words > 15000:
        for n in nodes:
            if n["target_words"] > 0:
                n["target_words"] = max(60, round(n["target_words"] * 12000 / before_words / 10) * 10)
    after_words = sum(n["target_words"] for n in nodes)
    if not deeper and before_words == after_words:
        return content, None
    report = {"promoted_sections": mapping, "original_target_words": before_words,
              "target_words": after_words, "original_nodes": len(original), "normalized_nodes": len(nodes),
              "scope": "仅调整标题层级、编号及篇幅预算，保留所有叶子任务与资产要求"}
    return json.dumps({"outline_plan": nodes}, ensure_ascii=False), report
