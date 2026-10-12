"""Export committed writing with supplied metadata using local tools only."""
import argparse
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("metadata", type=Path)
    args = parser.parse_args()

    # Fail closed if a dependency ever attempts a network request.
    def no_network(*args, **kwargs):
        raise RuntimeError("Offline export forbids network access")
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network

    from agent.assembly import AssemblyAgent
    from agent.research import assert_research_lock, digest
    from agent.writing.storage import input_fingerprint

    run = args.run.resolve()
    state = json.loads((run / "workspace/workflow/state.json").read_text())["state"]
    root = Path(state["workspace_dir"])
    manifest = json.loads((root / "writing/manifest.json").read_text())
    if manifest["input_fingerprint"] != input_fingerprint(state):
        raise ValueError("Writing manifest does not match checkpoint")
    assert_research_lock(state)
    if digest(state["bib_pool"]) != state["literature_sha256"]:
        raise ValueError("Bibliography changed")
    state["writing_records"] = manifest["records"]
    metadata = json.loads(args.metadata.read_text())
    allowed = {"abstract", "keywords", "topic_en", "abstract_en", "keywords_en", "acknowledgements"}
    if set(metadata) != allowed:
        raise ValueError("Supply exactly the six metadata fields")
    for key, value in metadata.items():
        if key in {"keywords", "keywords_en"}:
            if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                raise ValueError(key)
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(key)
    state.update(metadata)
    report = AssemblyAgent(state, state["assembly_contract"], state["abstract"], state["keywords"],
                           str(root / "assembly/final.docx")).invoke()
    audit = json.loads((root / "writing/asset-review.json").read_text())
    report.update(mode="offline_export", model_api_calls=0, metadata_source=str(args.metadata.resolve()),
                  full_workflow_review_complete=False, reviewed_image_versions=len(audit["reviews"]),
                  limitations=["Remaining image reviews were skipped at user request to export without paid APIs.",
                               "Metadata supplied locally from existing research and writing; no model API review.",
                               "This export does not mark the interrupted workflow as fully reviewed."])
    (root / "assembly/offline-export-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
