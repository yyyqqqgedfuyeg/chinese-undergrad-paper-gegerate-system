"""Uncommitted assets survive provider failures; semantic approval still happens per batch."""
import hashlib
import json
from pathlib import Path

from .schemas import WritingAsset
from .storage import asset_id, atomic_write, input_fingerprint, validate_assets
from .tools import workspace_path


def file_hashes(root, asset):
    return {asset[key]: hashlib.sha256(workspace_path(root, asset[key]).read_bytes()).hexdigest()
            for key in ("path", "source_path")}


def load_prepared(root: Path, state, tasks, constraints):
    path = root / "writing/prepared-assets.json"
    issued, instructions = {}, {}
    if not path.exists():
        return issued, instructions
    saved = json.loads(path.read_text())
    if saved.get("input_fingerprint") != input_fingerprint(state) or saved.get("constraints") != constraints:
        return issued, instructions
    allowed = {(t["section_id"], asset_id(a)) for t in tasks for a in t["planned_assets"]}
    for entry in saved["entries"]:
        asset = WritingAsset.model_validate(entry["asset"])
        key = (entry["section_id"], asset.asset_id)
        if key not in allowed:
            continue
        validate_assets(root, [asset])
        if file_hashes(root, asset.model_dump()) != entry["hashes"]:
            raise ValueError("未提交图表缓存被修改，不能复用")
        issued[key] = asset.model_dump()
        instructions[key] = entry["instructions"]
    return issued, instructions


def save_prepared(root: Path, state, constraints, issued, instructions):
    entries = [{"section_id": key[0], "asset": asset, "instructions": instructions[key],
                "hashes": file_hashes(root, asset)} for key, asset in issued.items()]
    atomic_write(root / "writing/prepared-assets.json", json.dumps({
        "input_fingerprint": input_fingerprint(state), "constraints": constraints,
        "entries": entries}, ensure_ascii=False, indent=2))
