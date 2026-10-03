"""产物校验与批次提交。manifest 是唯一提交点，失败批次不进入接力记录。"""

import hashlib
import json
from pathlib import Path
import re
import tempfile

from .schemas import BatchOutput, WritingRecord
from .tools import workspace_path


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_fingerprint(state: dict) -> str:
    value = {key: state.get(key) for key in
             ("project_id", "topic", "single_source_of_truth", "bib_pool")}
    value["outline_plan"] = [{k: v for k, v in task.items() if k != "status"}
                             for task in state["outline_plan"]]
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True))


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(content)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def asset_id(planned: str) -> str:
    match = re.match(r"[A-Za-z][A-Za-z0-9_-]*", planned.strip())
    if not match:
        raise ValueError(f"图表需求缺少开头标识符: {planned}")
    return match.group()


def validate_assets(root: Path, assets: list) -> None:
    for asset in assets:
        for value in (asset.source_path, asset.path):
            path = workspace_path(root, value)
            if not path.is_relative_to(root / "writing" / "assets"):
                raise ValueError(f"资产必须位于 writing/assets/: {value}")
            if not path.is_file() or not path.stat().st_size:
                raise ValueError(f"资产文件不存在或为空: {value}")
        if asset.kind in {"diagram", "ui"}:
            with workspace_path(root, asset.path).open("rb") as handle:
                header = handle.read(24)
            if not (header.startswith(b"\x89PNG\r\n\x1a\n") or header.startswith(b"\xff\xd8\xff")):
                raise ValueError(f"图片必须实际导出为 PNG/JPEG: {asset.path}")
        elif asset.kind == "table":
            load_table(workspace_path(root, asset.path))


def load_table(path: Path) -> dict:
    """表格作为结构化数据保存，DOCX 导出为可编辑的原生表格。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"columns", "rows"}:
        raise ValueError("表格 JSON 必须只包含 columns 和 rows")
    columns, rows = value["columns"], value["rows"]
    if not isinstance(columns, list) or not columns or not all(isinstance(c, str) and c.strip() for c in columns):
        raise ValueError("表格 columns 必须为非空列名列表")
    if not isinstance(rows, list) or not rows:
        raise ValueError("表格 rows 不能为空")
    if any(not isinstance(row, list) or len(row) != len(columns) or
           not all(isinstance(cell, str) for cell in row) for row in rows):
        raise ValueError("表格行的列数必须一致且单元格为字符串")
    return value


def parse_batch(content: str, tasks: list, state: dict, root: Path) -> BatchOutput:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    result = BatchOutput.model_validate_json(text)
    if [section.section_id for section in result.sections] != [t["section_id"] for t in tasks]:
        raise ValueError("输出必须按顺序完整包含本批所有小节，不能多写、漏写或重复")
    bib_keys = {entry["key"] for entry in state.get("bib_pool", [])}
    history_assets = {a["asset_id"]: a for r in state.get("writing_records", []) for a in r["assets"]}
    owned_paths = {a[k] for a in history_assets.values() for k in ("path", "source_path")}
    available_assets = set(history_assets)
    for section, task in zip(result.sections, tasks):
        if section.title != task["title"]:
            raise ValueError(f"标题与任务不一致: {section.section_id}")
        # 去掉引用、Markdown 标记后的非空字符作为中文正文长度近似；避免只有一句话却标完成。
        body = re.sub(r"\[\[.*?\]\]", "", section.content)
        length = len(re.sub(r"\s|[#*`|]", "", body))
        if not max(1, int(task["target_words"] * 0.6)) <= length <= task["target_words"] * 2:
            raise ValueError(f"{section.section_id} 正文长度 {length} 不在目标字数的 60%-200% 内")
        expected = [asset_id(value) for value in task["planned_assets"]]
        actual = [a.asset_id for a in section.assets]
        if len(actual) != len(set(actual)) or set(actual) != set(expected):
            raise ValueError(f"{section.section_id} 资产必须逐项覆盖 planned_assets: {expected}")
        for asset in section.assets:
            if asset.asset_id in available_assets:
                raise ValueError(f"资产标识重复: {asset.asset_id}")
            paths = {asset.path, asset.source_path}
            if paths & owned_paths:
                raise ValueError("不能覆盖其他资产的文件")
            owned_paths.update(paths)
            available_assets.add(asset.asset_id)
            marker = "REF_TABLE" if asset.kind == "table" else "REF_FIG"
            if f"[[{marker}:{asset.asset_id}]]" not in section.content:
                raise ValueError(f"正文未引用本节资产: {asset.asset_id}")
        validate_assets(root, section.assets)
        refs = set(re.findall(r"\[\[REF_CITE:([^\]]+)\]\]", section.content))
        if refs != set(section.citations) or not refs <= bib_keys:
            raise ValueError(f"{section.section_id} 文献引用与 citations / bib_pool 不一致")
        figure_refs = set(re.findall(r"\[\[REF_(?:FIG|TABLE):([^\]]+)\]\]", section.content))
        if not figure_refs <= available_assets:
            raise ValueError(f"未知图表引用: {figure_refs - available_assets}")
    return result


def validate_records(root: Path, records: list, tasks: list, state: dict) -> list[dict]:
    validated = [WritingRecord.model_validate(record).model_dump() for record in records]
    if len(validated) > len(tasks):
        raise ValueError("接力记录超过大纲长度")
    if [r["section_id"] for r in validated] != [t["section_id"] for t in tasks[:len(validated)]]:
        raise ValueError("接力记录必须是大纲已完成的连续前缀")
    for record in validated:
        path = workspace_path(root, record["content_path"])
        if record["content_path"] != f"writing/sections/{record['section_id']}.md":
            raise ValueError("正文路径不符合调度器约定")
        if not path.is_file() or path.read_text(encoding="utf-8") != record["content"]:
            raise ValueError(f"正文文件缺失或被修改: {record['content_path']}")
        if sha256(record["content"]) != record["content_sha256"]:
            raise ValueError("正文记录校验失败")
    if validated:
        # 结构化正文重新进行引用和资产检查。
        drafts = [{k: v for k, v in record.items() if k not in
                   {"content_path", "content_sha256", "node_index"}} for record in validated]
        parse_batch(json.dumps({"sections": drafts}, ensure_ascii=False), tasks[:len(validated)],
                    {**state, "writing_records": []}, root)
    return validated
