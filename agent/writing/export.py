"""将已验收的撰写记录装配为 DOCX，不调用模型重写正文。"""

import json
import os
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

from lxml import etree

from .storage import atomic_write, load_table, validate_records
from .tools import workspace_path


def export_docx(state: dict, output_path: str, abstract: str, keywords: list[str]) -> dict:
    root = Path(state["workspace_dir"]).resolve()
    leaves = [t for t in state["outline_plan"] if t["target_words"] > 0]
    records = validate_records(root, state.get("writing_records", []), leaves, state)
    if len(records) != len(leaves) or not abstract.strip() or not keywords:
        raise ValueError("正文未完成或缺少摘要/关键词，不能导出成稿")
    payload = {"topic": state["topic"], "abstract": abstract, "keywords": keywords,
               "outline": state["outline_plan"], "records": records, "bib_pool": state.get("bib_pool", [])}
    for record in records:
        for asset in record["assets"]:
            if asset["kind"] == "table":
                asset["data"] = load_table(workspace_path(root, asset["path"]))
            else:
                asset["absolute_path"] = str(workspace_path(root, asset["path"]))
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload_path = output.with_suffix(".input.json")
    atomic_write(payload_path, json.dumps(payload, ensure_ascii=False, indent=2))
    env = dict(os.environ)
    modules = Path(__file__).resolve().parents[2] / ".tools/docx/node_modules"
    env["NODE_PATH"] = str(modules) + (os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    subprocess.run(["node", str(Path(__file__).with_name("export_docx.cjs")), str(payload_path), str(output)],
                   env=env, check=True, capture_output=True, text=True, timeout=90)
    return validate_docx(output, payload)


def validate_docx(path: Path, payload: dict) -> dict:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}
    with ZipFile(path) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        text = "".join(document.xpath("//w:t/text()", namespaces=ns))
        if re.search(r"\[\[REF_|待补充|TODO|PLACEHOLDER", text, re.IGNORECASE):
            raise ValueError("成稿包含未解析引用或占位内容")
        missing = [item["title"] for item in payload["outline"] if item["title"] not in text]
        if missing:
            raise ValueError(f"DOCX 缺少标题: {missing}")
        # 正文完整性：移除标记后的所有正文字符都应按顺序存在；不以字数代替内容检查。
        for record in payload["records"]:
            for paragraph in re.split(r"\n\s*\n", record["content"]):
                normalized = re.sub(r"\s", "", text)
                # 引用内插入图/表号，分段核对确保原文未丢失。
                parts = re.split(r"\[\[REF_[A-Z]+:[^\]]+\]\]", paragraph)
                for part in parts:
                    part = re.sub(r"[*`#\s]", "", part)
                    if part and part not in re.sub(r"[*`#]", "", normalized):
                        raise ValueError(f"DOCX 正文内容不完整: {record['section_id']}: {part[:60]}")
        assets = [a for r in payload["records"] for a in r["assets"]]
        expected_tables = sum(a["kind"] == "table" for a in assets)
        tables = document.xpath("//w:tbl", namespaces=ns)
        images = document.xpath("//a:blip", namespaces=ns)
        if len(tables) != expected_tables or len(images) != len(assets) - expected_tables:
            raise ValueError("DOCX 图表数量与写作产物不一致")
        for paragraph in document.xpath("//w:p[w:r/w:drawing]", namespaces=ns):
            spacing = paragraph.find("w:pPr/w:spacing", namespaces=ns)
            extent = paragraph.find("w:r/w:drawing/wp:inline/wp:extent", namespaces=ns)
            if spacing is None or extent is None or spacing.get(f"{{{ns['w']}}}lineRule") != "atLeast":
                raise ValueError("图片段落必须显式保留最小行高，防止正文行距裁切图片")
            if int(spacing.get(f"{{{ns['w']}}}line", "0")) < int(extent.get("cy")) / 635:
                raise ValueError("图片段落行高不足以容纳整图")
        for table in tables:
            for name in ("insideH", "insideV", "left", "right"):
                border = table.find(f"w:tblPr/w:tblBorders/w:{name}", namespaces=ns)
                if border is None or border.get(f"{{{ns['w']}}}val") not in {"nil", "none"}:
                    raise ValueError("原生表格不符合三线表边框要求")
        for asset in assets:
            if asset["kind"] == "table":
                for row in [asset["data"]["columns"]] + asset["data"]["rows"]:
                    if any(value not in text for value in row):
                        raise ValueError("DOCX 丢失表格单元格内容")
        media = [name for name in archive.namelist() if name.startswith("word/media/") and not name.endswith("/")]
    return {"path": str(path), "sections": len(payload["records"]), "figures": len(images),
            "tables": len(tables), "embedded_media": len(media), "text_characters": len(text),
            "content_complete": True, "references_resolved": True, "native_three_line_tables": True}
