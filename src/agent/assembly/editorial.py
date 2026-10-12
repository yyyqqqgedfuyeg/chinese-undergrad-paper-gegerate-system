"""Local, explicit editorial revisions; retain original checkpoint and assets."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile

from ..security.sandbox import CodingSandbox

from ..writing.storage import input_fingerprint, validate_records
from ..writing.prepared_assets import file_hashes
from ..research import assert_research_lock


def unparenthesize(value):
    # Preserve constraints, state meanings and qualifications instead of deleting them.
    value = re.sub(r"[（(]", "，", value)
    value = re.sub(r"[）)]", "", value)
    return re.sub(r"，\s*([，。；：])", r"\1", value)


def clean_diagram_labels(root, asset, override=None, monochrome=False):
    """Rerender source diagrams locally; never edit bitmap pixels or use APIs."""
    source = root / asset["source_path"]
    code = source.read_text()
    suffix = source.suffix
    if override is not None:
        if isinstance(override, dict):
            code, suffix = override["code"], override["suffix"]
        else:
            code, suffix = override, ".dot"
    if suffix == ".dot":
        code = re.sub(r'"(?:\\.|[^"\\])*"', lambda m: re.sub(r"[（）()]", " ", m.group()), code)
        if monochrome:
            code = re.sub(r'(fillcolor|bgcolor|fontcolor|color)\s*=\s*("[^"\n]*"|[A-Za-z0-9#]+)',
                          lambda m: m[1] + '= "' + ('white' if m[1] in {'fillcolor','bgcolor'} else 'black') + '"', code)
        command = "dot -Tpng source.dot -o output.png"
    elif suffix == ".py":
        # Only visible labels are changed; business logic and coordinates remain intact.
        prelude = '''import matplotlib
matplotlib.use("Agg")
from matplotlib.axes import Axes
from matplotlib.figure import Figure
import re as _label_re
def _clean_label(value):
    return _label_re.sub(r"[（）()]", " ", value) if isinstance(value, str) else value
_original_text = Axes.text
def _text(self, x, y, s, *args, **kwargs):
    return _original_text(self, x, y, _clean_label(s), *args, **kwargs)
Axes.text = _text
_original_annotate = Axes.annotate
def _annotate(self, text, *args, **kwargs):
    return _original_annotate(self, _clean_label(text), *args, **kwargs)
Axes.annotate = _annotate
_original_save = Figure.savefig
def _save(self, fname, *args, **kwargs):
    _original_save(self, fname, *args, **kwargs)
    return _original_save(self, "/workspace/output.png", *args, **kwargs)
Figure.savefig = _save
'''
        if monochrome:
            prelude = prelude.replace('    _original_save(self, fname, *args, **kwargs)', """    from matplotlib.text import Text
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch, FancyArrowPatch
    from matplotlib.collections import Collection
    for artist in self.findobj():
        if isinstance(artist, Text):
            artist.set_color('black')
            arrow = getattr(artist, 'arrow_patch', None)
            if arrow is not None: arrow.set_color('black')
        elif isinstance(artist, Line2D):
            artist.set_color('black')
            artist.set_markeredgecolor('black')
            artist.set_markerfacecolor('white')
        elif isinstance(artist, Patch):
            artist.set_facecolor('black' if isinstance(artist, FancyArrowPatch) else 'white')
            artist.set_edgecolor('black')
            artist.set_alpha(1)
        elif isinstance(artist, Collection):
            artist.set_edgecolor('black')
            artist.set_facecolor('white')
    self.set_facecolor('white')
    kwargs['facecolor'] = 'white'
    _original_save(self, fname, *args, **kwargs)""")
        code = prelude + "\n" + code
        command = "python source.py"
    else:
        raise ValueError("Unsupported diagram source: " + suffix)
    with tempfile.TemporaryDirectory(prefix="paper-labels-") as folder:
        work = Path(folder)
        (work / ("source" + suffix)).write_text(code)
        result = json.loads(CodingSandbox(work).run(command, timeout_seconds=60))
        if result["exit_code"] or not (work / "output.png").is_file():
            raise ValueError("Local diagram rendering failed: " + asset["asset_id"] + str(result))
        from PIL import Image
        with Image.open(work / "output.png") as im:
            im.verify()
        shutil.copyfile(work / "output.png", root / asset["path"])
        if source.suffix != suffix:
            source = source.with_suffix(suffix)
            asset["source_path"] = str(source.relative_to(root))
        source.write_text(code)


def revise(state, manifest, destination, plan):
    """Apply a reviewed JSON plan in a new workspace, never to the input run.

    Plan: titles, omit, replacements, additions, captions, table_overrides,
    layout_options. Replacements map section id to authored replacement prose.
    All retained content is revalidated after fresh hashes are computed.
    """
    state = deepcopy(state)
    if manifest["input_fingerprint"] != input_fingerprint(state):
        raise ValueError("Editorial input does not match the committed manifest")
    assert_research_lock(state)
    source = Path(state["workspace_dir"]).resolve()
    root = Path(destination).resolve()
    if root == source or root.is_relative_to(source) or root.exists():
        raise ValueError("Use a new independent workspace for editorial revisions")
    records = validate_records(source, manifest["records"],
                               [n for n in state["outline_plan"] if n["target_words"]], state)
    root.mkdir(parents=True)
    shutil.copytree(source / "writing/assets", root / "writing/assets")
    state["workspace_dir"] = str(root)
    state["layout_options"] = plan.get("layout_options", {})
    omitted = plan.get("omit", [])
    nodes = [n for n in state["outline_plan"] if not any(
        n["section_id"] == sid or n["section_id"].startswith(sid + ".") for sid in omitted)]
    by_id = {r["section_id"]: r for r in records}
    for sid, content in plan.get("replacements", {}).items():
        descendants = [n for n in nodes if n["section_id"].startswith(sid + ".")]
        nodes = [n for n in nodes if n not in descendants]
        seed = by_id.get(sid) or next(by_id[n["section_id"]] for n in descendants if n["section_id"] in by_id)
        by_id[sid] = {**deepcopy(seed), "section_id": sid, "content": content,
                      "assets": deepcopy(plan.get("replacement_assets", {}).get(sid, seed["assets"]))}
    for node in plan.get("additions", []):
        node = deepcopy(node)
        content = node.pop("content")
        nodes.append(node)
        by_id[node["section_id"]] = {"section_id": node["section_id"], "content": content,
            "title": node["title"], "summary": content, "key_facts": [], "assets": [], "citations": []}
    nodes.sort(key=lambda n: tuple(map(int, n["section_id"].split("."))))
    revised = []
    for node in nodes:
        sid = node["section_id"]
        node["title"] = plan.get("titles", {}).get(sid, node["title"])
        children = any(n["section_id"].startswith(sid + ".") for n in nodes)
        if children:
            node.update(target_words=0, planned_assets=[])
            continue
        record = deepcopy(by_id[sid])
        record.update(title=node["title"], content=unparenthesize(record["content"]))
        record["summary"] = unparenthesize(record["summary"])
        for asset in record["assets"]:
            asset["description"] = plan["captions"][asset["asset_id"]]
            if asset["kind"] != "table" and plan.get("clean_diagram_labels"):
                clean_diagram_labels(root, asset, plan.get("diagram_sources", {}).get(asset["asset_id"]), plan.get("monochrome_diagrams", False))
            if asset["kind"] == "table":
                path = root / asset["path"]
                table = plan.get("table_overrides", {}).get(asset["asset_id"]) or json.loads(path.read_text())
                table = {"columns": [unparenthesize(c).replace("|", "、") for c in table["columns"]],
                         "rows": [[unparenthesize(c).replace("|", "；") for c in row] for row in table["rows"]]}
                for name in {asset["path"], asset["source_path"]}:
                    (root / name).write_text(json.dumps(table, ensure_ascii=False, indent=2))
        record["citations"] = list(dict.fromkeys(re.findall(r"\[\[REF_CITE:([^\]]+)\]\]", record["content"])))
        record["content_path"] = f"writing/sections/{sid}.md"
        path = root / record["content_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record["content"])
        record["content_sha256"] = sha256(record["content"].encode()).hexdigest()
        record["asset_sha256"] = {k: v for a in record["assets"] for k, v in file_hashes(root, a).items()}
        record["node_index"] = len(revised) + 1
        revised.append(record)
        node["target_words"] = max(1, len(re.sub(r"\[\[.*?\]\]|\s", "", record["content"])))
        node["planned_assets"] = [a["asset_id"] + " " + a["description"] for a in record["assets"]]
    state["outline_plan"] = nodes
    # Renumber remaining siblings after deletions; asset IDs remain stable.
    counters, numbering = {}, {}
    for node in nodes:
        old = node["section_id"]
        parent = old.rpartition(".")[0]
        counters[parent] = counters.get(parent, 0) + 1
        numbering[old] = (numbering[parent] + "." if parent else "") + str(counters[parent])
        node["section_id"] = numbering[old]
    for record in revised:
        record["section_id"] = numbering[record["section_id"]]
        record["content_path"] = f"writing/sections/{record['section_id']}.md"
        (root / record["content_path"]).write_text(record["content"])
    state["writing_records"] = revised
    state["writing_report"] = {"complete": True, "completed_sections": len(revised),
        "total_sections": len(revised), "mode": "offline_editorial_revision"}
    for key in ("outline_review", "metadata_review", "asset_review_report", "assembly_report", "final_doc_path"):
        state.pop(key, None)
    validate_records(root, revised, [n for n in nodes if n["target_words"]], state)
    state["editorial_report"] = {"source_workspace": str(source), "model_api_calls": 0,
        "plan": plan, "sections": len(revised), "semantic_review": "local editorial revision, not model reapproval"}
    state["workflow_report"] = {"status": "offline_editorial_export", "completed_stages": []}
    (root / "workflow").mkdir()
    (root / "workflow/state.json").write_text(json.dumps({"state": state}, ensure_ascii=False, indent=2))
    (root / "writing/manifest.json").write_text(json.dumps({"input_fingerprint": input_fingerprint(state),
        "records": revised}, ensure_ascii=False, indent=2))
    (root / "editorial-report.json").write_text(json.dumps(state["editorial_report"], ensure_ascii=False, indent=2))
    return state
