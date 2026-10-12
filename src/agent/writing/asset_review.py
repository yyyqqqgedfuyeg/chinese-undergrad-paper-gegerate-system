"""Final image review and audited replacement of individual committed assets."""
from copy import deepcopy
import json
from pathlib import Path

from ..assembly.engine import asset_constraints
from ..coding import CodingAgent
from ..paper_routing import routing_context
from ..research import assert_research_lock, digest, review_consistency
from .agent import WritingAgent
from .prepared_assets import file_hashes
from .storage import atomic_write, input_fingerprint, validate_records


class FinalAssetReviewAgent:
    def __init__(self, llm, coder=None, max_repairs=3):
        self.llm = llm
        self.coder = coder or CodingAgent(llm=llm)
        self.max_repairs = max_repairs

    def invoke(self, state):
        assert_research_lock(state)
        root = Path(state["workspace_dir"])
        manifest_path = root / "writing/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest["input_fingerprint"] != input_fingerprint(state):
            raise ValueError("图表复查输入与正文记录不一致")
        tasks = WritingAgent._tasks(state)
        records = validate_records(root, manifest["records"], tasks, state)
        audit_path = root / "writing/asset-review.json"
        audit = json.loads(audit_path.read_text()) if audit_path.exists() else {"reviews": {}, "replacements": []}
        constraints = asset_constraints(state)

        def save_audit():
            atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2))

        for ri, record in enumerate(records):
            for ai, initial in enumerate(record["assets"]):
                if initial["kind"] == "table":
                    continue
                asset = initial
                for attempt in range(self.max_repairs + 1):
                    identity = digest({"research": state["research_lock"]["sha256"],
                        "section": record["content_sha256"], "asset": asset,
                        "files": file_hashes(root, asset)})
                    if identity in audit["reviews"]:
                        break
                    try:
                        review = review_consistency(self.llm, state,
                            {"section": {**record, "assets": [asset]},
                             "source": (root / asset["source_path"]).read_text(encoding="utf-8"),
                             "render_constraints": constraints,
                             "check": "检查实际图片中的中文缺字/方框、裁切、重叠遮挡、连线方向与技术流程错误，以及与正文和冻结事实的一致性。"},
                            images=[{"asset_id": asset["asset_id"], "path": str(root / asset["path"])}])
                        audit["reviews"][identity] = review
                        save_audit()
                        break
                    except ValueError as exc:
                        audit.setdefault("rejections", []).append({"identity": identity,
                            "asset_id": asset["asset_id"], "error": str(exc)})
                        save_audit()
                        if attempt == self.max_repairs:
                            raise ValueError(f"成稿图表复查未通过 {asset['asset_id']}: {exc}") from exc
                        asset = self.coder.run_asset({**routing_context(state), "section_id": record["section_id"],
                            "asset_id": initial["asset_id"], "requirement": initial["description"],
                            "previous_source_path": asset["source_path"],
                            "single_source_of_truth": state["single_source_of_truth"],
                            "render_constraints": constraints,
                            "instructions": "只修复图表，不改变已确定的研究方案。正文：" + record["content"]
                                + "。审查反馈：" + str(exc)}, str(root))
                if asset != initial:
                    candidate = deepcopy(records)
                    updated = candidate[ri]
                    updated["assets"][ai] = asset
                    updated["asset_sha256"] = {path: value for a in updated["assets"]
                                               for path, value in file_hashes(root, a).items()}
                    validate_records(root, candidate, tasks, state)
                    # Archive the exact old record before the manifest commit point.
                    audit["replacements"].append({"section_id": record["section_id"],
                        "before": initial, "after": asset, "review_identity": identity})
                    save_audit()
                    manifest["records"] = candidate
                    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
                    records = candidate
        state["writing_records"] = records
        state["asset_review_report"] = {"passed": True, "images": sum(
            a["kind"] != "table" for r in records for a in r["assets"]),
            "replacements": len(audit["replacements"]), "audit_path": str(audit_path)}
        return state
