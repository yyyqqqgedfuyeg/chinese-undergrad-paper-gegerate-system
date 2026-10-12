"""从模板原型装配正文，只变更绑定内容和新增媒体，不重建模板格式。"""
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from lxml import etree as E

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS = {"w": W, "r": R, "a": A, "wp": WP,
      "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture"}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def parse(data):
    return E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True))


def xml(node):
    return E.tostring(node, xml_declaration=True, encoding="UTF-8", standalone=True)


def text(node):
    return "".join(node.xpath(".//w:t/text()", namespaces=NS))


def package(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("模板 ZIP 含重复部件")
        return {name: archive.read(name) for name in names}


def archive_bytes(parts):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, parts[name])
    return stream.getvalue()


def set_text(node, value):
    """保留原型全部 pPr/rPr；只替换文本节点。拒绝含域/链接的内容原型。"""
    if node.xpath(".//w:fldChar|.//w:fldSimple|.//w:hyperlink|.//w:sectPr", namespaces=NS):
        raise ValueError("内容原型不能包含域、链接或分节符")
    nodes = node.xpath(".//w:t", namespaces=NS)
    if not nodes:
        raise ValueError("内容原型缺少文本 run")
    nodes[0].text = value
    nodes[0].set(XML_SPACE, "preserve")
    for child in nodes[1:]:
        child.text = ""


def paragraph_property(paragraph, name, **attrs):
    """Set an explicit layout override without altering template styles."""
    ppr = paragraph.find("w:pPr", NS)
    if ppr is None:
        ppr = E.Element("{" + W + "}pPr")
        paragraph.insert(0, ppr)
    node = ppr.find("w:" + name, NS)
    if node is None:
        node = E.Element("{" + W + "}" + name)
        order = "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange".split()
        rank = order.index(name)
        index = next((i for i, child in enumerate(ppr) if E.QName(child).localname in order and order.index(E.QName(child).localname) > rank), len(ppr))
        ppr.insert(index, node)
    for key, value in attrs.items():
        node.set("{" + W + "}" + key, str(value))
    return node


def inline_content(paragraph, chunks):
    """原生 REF/SEQ 使用原型文本 run 的属性，不引入新的字体/样式。"""
    first = paragraph.xpath(".//w:r[w:t]", namespaces=NS)[0]
    parent = first.getparent()
    index = parent.index(first)
    props = first.find("w:rPr", NS)
    parent.remove(first)
    for chunk in chunks:
        kind = chunk[0]
        if kind in {"start", "end"}:
            node = E.Element("{"+W+"}bookmark"+("Start" if kind == "start" else "End"))
            node.set("{"+W+"}id", str(chunk[1]))
            if kind == "start":
                node.set("{"+W+"}name", chunk[2])
        else:
            run = E.Element("{"+W+"}r")
            if props is not None:
                run.append(deepcopy(props))
            value = chunk[1] if kind == "text" else chunk[2]
            E.SubElement(run, "{"+W+"}t", {XML_SPACE: "preserve"}).text = value
            if kind == "cite":
                rpr = run.find("w:rPr", NS)
                if rpr is None:
                    rpr = E.Element("{" + W + "}rPr")
                    run.insert(0, rpr)
                for old in rpr.findall("w:vertAlign", NS):
                    rpr.remove(old)
                E.SubElement(rpr, "{" + W + "}vertAlign", {"{" + W + "}val": "superscript"})
            if kind == "text":
                node = run
            else:
                node = E.Element("{"+W+"}fldSimple")
                instruction = ("REF " + chunk[1] + " \\h") if kind in {"ref", "cite"} else ("SEQ " + chunk[1] + " \\* ARABIC")
                node.set("{"+W+"}instr", instruction)
                node.append(run)
        parent.insert(index, node); index += 1


def replace_token(node, token, value):
    """跨 run 替换占位符，保留每个 run 格式和周围文本。"""
    nodes = node.xpath(".//w:t", namespaces=NS)
    joined = "".join(n.text or "" for n in nodes)
    while token in joined:
        start = joined.index(token); end = start + len(token)
        offset = 0
        for item in nodes:
            old = item.text or ""
            left, right = offset, offset + len(old)
            if left < end and right > start:
                item.text = old[:max(0, start-left)] + (value if left <= start < right else "") + old[max(0, end-left):]
                item.set(XML_SPACE, "preserve")
            offset = right
        joined = "".join(n.text or "" for n in nodes)


def assemble(template: Path, contract: dict, state: dict, abstract: str, keywords: list[str]):
    from ..writing.storage import validate_records, load_table
    from ..writing.tools import workspace_path
    root = Path(state["workspace_dir"]).resolve()
    parts = package(template)
    before = dict(parts)
    fingerprint = sha256(template.read_bytes()).hexdigest()
    if contract.get("template_sha256") != fingerprint:
        raise ValueError("模板指纹与装配绑定不一致；需要重新确认原型")
    records = validate_records(root, state.get("writing_records", []),
                               [t for t in state["outline_plan"] if t["target_words"] > 0], state)
    if len(records) != sum(t["target_words"] > 0 for t in state["outline_plan"]):
        raise ValueError("正文未完整验收")
    if not abstract.strip() or not keywords:
        raise ValueError("缺少上游摘要或关键词")
    document = parse(parts["word/document.xml"])
    body = document.find("w:body", NS)
    paragraphs = list(body.findall("w:p", NS))
    render_constraints = asset_constraints({**state, "assembly_contract": contract, "new_template_path": str(template)})

    def select(value):
        matches = [p for p in paragraphs if text(p) == value]
        if len(matches) != 1:
            raise ValueError(f"段落锚点必须唯一：{value}")
        return matches[0]

    anchor = select(contract["body_marker"])
    if anchor.find("w:pPr/w:sectPr", NS) is not None:
        raise ValueError("正文锚点不能携带分节符")
    prototypes = {name: select(marker) for name, marker in contract["paragraphs"].items()}
    if len({id(p) for p in prototypes.values()} | {id(anchor)}) != len(prototypes) + 1:
        raise ValueError("原型与正文锚点不能重叠")
    table_prototypes = {}
    tables = body.findall("w:tbl", NS)
    for count, index in contract.get("tables", {}).items():
        if type(index) is not int or not 0 <= index < len(tables):
            raise ValueError("无效表格原型索引")
        table_prototypes[int(count)] = tables[index]
    if any(p.xpath(".//w:sectPr", namespaces=NS) for p in prototypes.values()):
        raise ValueError("段落原型不能携带分节符")
    blocks = []
    clone_counts = {}
    bookmark_id = max([int(v) for v in document.xpath(".//w:bookmarkStart/@w:id", namespaces=NS)] + [-1]) + 1

    def clone_prototype(name):
        if name not in prototypes:
            raise ValueError(f"模板缺少段落原型：{name}")
        p = deepcopy(prototypes[name])
        count = clone_counts.get(name, 0)
        clone_counts[name] = count + 1
        if count:
            # 模板原有书签随首个实例保留，后续实例不复制这些全局标识。
            # 新图表/文献的引用使用装配器生成的独立书签。
            for marker in p.xpath(".//w:bookmarkStart|.//w:bookmarkEnd", namespaces=NS):
                marker.getparent().remove(marker)
        return p

    def paragraph(name, value):
        if name not in prototypes:
            raise ValueError(f"模板缺少段落原型：{name}")
        p = clone_prototype(name); set_text(p, value)
        blocks.append(p)
        return p

    assets = {a["asset_id"]: a for r in records for a in r["assets"]}
    counters = {"table": 0, "figure": 0}
    labels = {}
    for aid, asset in assets.items():
        key = "table" if asset["kind"] == "table" else "figure"
        counters[key] += 1
        labels[aid] = ("表" if key == "table" else "图") + str(counters[key])
    pool = {v["key"]: v for v in state.get("bib_pool", [])}
    cited_keys = dict.fromkeys(key for record in records
                              for key in re.findall(r"\[\[REF_CITE:([^\]]+)\]\]", record["content"]))
    bib = {key: (i+1, pool[key]) for i, key in enumerate(cited_keys)}
    rel_name = "word/_rels/document.xml.rels"
    relationships = parse(parts[rel_name])
    types = parse(parts["[Content_Types].xml"])
    next_id = max([int(v) for v in document.xpath(".//wp:docPr/@id", namespaces=NS)] + [0]) + 1
    added_media = []
    emitted = set()
    existing_names = set(document.xpath(".//w:bookmarkStart/@w:name", namespaces=NS))
    def bookmark_name(category, key):
        name = "Paper" + category + sha256(key.encode()).hexdigest()[:24]
        if name in existing_names:
            raise ValueError("装配书签名称与模板冲突")
        return name
    asset_names = {key: bookmark_name("Asset", key) for key in assets}
    bib_names = {key: bookmark_name("Bib", key) for key in bib}

    def caption(aid, kind):
        nonlocal bookmark_id
        value = labels[aid] + " " + assets[aid]["description"]
        p = paragraph(kind+"_caption", value)
        number = labels[aid][1:]
        inline_content(p, [("start", bookmark_id, asset_names[aid]),
            ("text", labels[aid][0]), ("seq", "Paper"+kind.title(), number),
            ("end", bookmark_id), ("text", " "+assets[aid]["description"])])
        bookmark_id += 1

    def emit_asset(aid):
        nonlocal next_id
        if aid in emitted:
            return
        emitted.add(aid)
        asset = assets[aid]
        if asset["kind"] == "table":
            caption(aid, "table")
            data = load_table(workspace_path(root, asset["path"]))
            count = len(data["columns"])
            if count not in table_prototypes:
                raise ValueError(f"模板缺少 {count} 列表格原型，禁止自行推断表格格式")
            table = deepcopy(table_prototypes[count])
            rows = table.findall("w:tr", NS)
            if len(rows) < 2:
                raise ValueError("表格原型至少要有表头和数据行")
            for row in rows:
                table.remove(row)
            values = [data["columns"]] + data["rows"]
            if len(values) > 2 and len(rows) == 2:
                # A two-row grid table has a reusable data-row prototype. A
                # special last-row bottom border is ambiguous: reject that case.
                if rows[1].xpath(".//w:tcBorders/w:bottom", namespaces=NS):
                    raise ValueError("两行表格含末行专用边框，需要独立普通行原型")
            for i, row_values in enumerate(values):
                # 第一行继承表头，末行继承模板末行底边框，普通行继承第二行。
                original = rows[0] if i == 0 else (rows[-1] if i == len(values)-1 else rows[1])
                row = deepcopy(original)
                cells = row.findall("w:tc", NS)
                if len(cells) != count or row.xpath(".//w:gridSpan|.//w:vMerge|.//w:hMerge", namespaces=NS):
                    raise ValueError("表格原型列数不匹配或含合并单元格")
                for cell, value in zip(cells, row_values):
                    if len(cell.findall("w:p", NS)) != 1:
                        raise ValueError("表格原型每个单元格须有一个文本段落")
                    set_text(cell, value)
                table.append(row)
            blocks.append(table)
        else:
            if "figure" not in prototypes:
                raise ValueError("模板缺少图片原型")
            p = clone_prototype("figure")
            paragraph_property(p, "spacing", line="240", lineRule="auto")
            paragraph_property(p, "snapToGrid", val="0")
            paragraph_property(p, "keepNext", val="1")
            for marker in p.xpath(".//w:t", namespaces=NS):
                marker.text = ""
            blips = p.xpath(".//a:blip", namespaces=NS)
            if len(blips) != 1:
                raise ValueError("图片原型必须恰含一张内嵌图片")
            path = workspace_path(root, asset["path"])
            from PIL import Image
            with Image.open(path) as im:
                extents = p.xpath(".//wp:extent", namespaces=NS)
                if len(extents) != 1:
                    raise ValueError("图片原型缺少显示尺寸")
                ratio = render_constraints.get("image_aspect_ratio")
                if ratio and abs(im.width / im.height / ratio - 1) > 0.01:
                    raise ValueError("图片宽高比不匹配模板，需编码阶段重新生成")
                if render_constraints.get("image_sizing") == "fit_width":
                    width = render_constraints["image_max_width_emu"]
                    height = round(width * im.height / im.width)
                    maximum = render_constraints.get("image_max_height_emu")
                    if maximum and height > maximum:
                        width = round(width * maximum / height)
                        height = maximum
                    for extent in [*extents, *p.xpath(".//pic:spPr/a:xfrm/a:ext", namespaces=NS)]:
                        extent.set("cx", str(width))
                        extent.set("cy", str(height))
                im.verify()
                extension = {"PNG": "png", "JPEG": "jpg"}.get(im.format)
            if not extension:
                raise ValueError("图片必须为 PNG/JPEG")
            payload = path.read_bytes()
            name = f"word/media/assembled_{sha256(payload).hexdigest()}.{extension}"
            parts[name] = payload
            added_media.append(name)
            rid = f"rIdAssembled{len(added_media)}"
            if any(r.get("Id") == rid for r in relationships):
                raise ValueError("图片 relationship 标识冲突")
            E.SubElement(relationships, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship",
                Id=rid, Type=R+"/image", Target=name.removeprefix("word/"))
            blips[0].set("{"+R+"}embed", rid)
            for prop in p.xpath(".//wp:docPr", namespaces=NS):
                prop.set("id", str(next_id)); next_id += 1
            # 复用段落/图片样式；默认保持素材比例，以模板宽度和版心高度为上限。
            blocks.append(p)
            caption(aid, "figure")
            if not any(t.get("Extension") == extension for t in types):
                E.SubElement(types, "{http://schemas.openxmlformats.org/package/2006/content-types}Default",
                             Extension=extension, ContentType="image/" + ("jpeg" if extension == "jpg" else "png"))

    record_map = {r["section_id"]: r for r in records}
    used_citations = set()
    for item in state["outline_plan"]:
        sid = item["section_id"]
        heading = item["title"]
        prototype = prototypes.get("heading" + str(sid.count(".") + 1))
        auto_numbered = prototype is not None and prototype.find("w:pPr/w:numPr", NS) is not None
        if "." in sid and not auto_numbered and not re.match(r"^" + re.escape(sid) + r"(?:\s|[、.．]|$)", heading):
            heading = sid + " " + heading
        heading_p = paragraph("heading"+str(sid.count(".")+1), heading)
        paragraph_property(heading_p, "keepNext", val="1")
        if "." not in sid and state.get("layout_options", {}).get("chapter_page_break", False):
            paragraph_property(heading_p, "pageBreakBefore", val="1")
        if not item["target_words"]:
            continue
        content = record_map[item["section_id"]]["content"]
        for line in re.split(r"\n\s*\n", content):
            inserts = []
            def replace(match):
                kind, key = match.groups()
                if kind == "CITE":
                    if key not in bib:
                        raise ValueError("未知文献引用")
                    used_citations.add(key)
                    return f"[{bib[key][0]}]"
                if key not in assets:
                    raise ValueError("未知图表引用")
                if (kind == "TABLE") != (assets[key]["kind"] == "table"):
                    raise ValueError("图表引用类型错误")
                inserts.append(key)
                return labels[key]
            value = re.sub(r"\[\[REF_(CITE|FIG|TABLE):([^\]]+)\]\]", replace, line)
            if value.strip():
                p = paragraph("body", value)
                chunks = []
                last = 0
                for match in re.finditer(r"\[\[REF_(CITE|FIG|TABLE):([^\]]+)\]\]", line):
                    kind, key = match.groups()
                    chunks.append(("text", line[last:match.start()]))
                    name = bib_names[key] if kind == "CITE" else asset_names[key]
                    cached = f"[{bib[key][0]}]" if kind == "CITE" else labels[key]
                    chunks.append(("cite" if kind == "CITE" else "ref", name, cached))
                    last = match.end()
                if chunks:
                    chunks.append(("text", line[last:]))
                    inline_content(p, chunks)
            for aid in inserts:
                emit_asset(aid)
    if emitted != set(assets):
        raise ValueError("存在未装配图表")
    if used_citations:
        paragraph("bibliography_heading", "参考文献")
        for key, (number, item) in bib.items():
            if key not in used_citations:
                continue
            formatted = item.get("formatted") or item.get("citation")
            if not formatted:
                authors = item.get("authors", [])
                if not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
                    raise ValueError("文献 authors 必须为字符串列表")
                formatted = f"{', '.join(authors)}. {item['title']}. {item.get('venue', item.get('journal', ''))}, {item['year']}. {item.get('doi', '')}".strip()
            if state.get("layout_options", {}).get("no_parentheses"):
                from .editorial import unparenthesize
                formatted = unparenthesize(formatted)
            p = paragraph("body", f"[{number}] {formatted}")
            paragraph_property(p, "outlineLvl", val="9")
            inline_content(p, [("start", bookmark_id, bib_names[key]), ("text", f"[{number}]"),
                               ("end", bookmark_id), ("text", " "+formatted)])
            bookmark_id += 1

    position = body.index(anchor)
    for p in blocks:
        body.insert(position, p); position += 1
    for p in {anchor, *prototypes.values(), *table_prototypes.values()}:
        body.remove(p)
    parts["word/document.xml"] = xml(document)
    if added_media:
        parts[rel_name] = xml(relationships)
        parts["[Content_Types].xml"] = xml(types)
    fields = contract.get("fields", {})
    values = {"topic": state["topic"], "abstract": abstract, "keywords": "；".join(keywords)}
    for key in ("topic_en", "abstract_en", "keywords_en", "acknowledgements"):
        if key in fields.values():
            value = state.get(key)
            if key == "keywords_en":
                if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
                    raise ValueError("缺少英文关键词")
                value = "; ".join(value)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"缺少元信息：{key}")
            values[key] = value
    counts = {token: 0 for token in fields}
    for name in before:
        if not re.fullmatch(r"word/(document|header\d+|footer\d+)\.xml", name):
            continue
        tree = parse(parts[name]); changed = False
        for p in tree.xpath(".//w:p", namespaces=NS):
            for token, key in fields.items():
                if not token or key not in values or token in values[key]:
                    raise ValueError("无效元信息绑定")
                if token in text(p):
                    counts[token] += text(p).count(token)
                    replace_token(p, token, values[key]); changed = True
                    # Inline abstract/keyword content is not a heading, even
                    # when its template style inherits an outline level.
                    # Keep the named style untouched; override only TOC scope.
                    if key in {"abstract", "abstract_en", "keywords", "keywords_en", "acknowledgements"}:
                        ppr = p.find("w:pPr", NS)
                        if ppr is None:
                            ppr = E.Element("{" + NS["w"] + "}pPr")
                            p.insert(0, ppr)
                        level = ppr.find("w:outlineLvl", NS)
                        if level is None:
                            level = E.Element("{" + NS["w"] + "}outlineLvl")
                            later = ppr.find("w:rPr", NS)
                            if later is None:
                                later = ppr.find("w:sectPr", NS)
                            ppr.insert(ppr.index(later) if later is not None else len(ppr), level)
                        level.set("{" + NS["w"] + "}val", "9")
        if changed:
            parts[name] = xml(tree)
    if any(v == 0 for v in counts.values()):
        raise ValueError("元信息绑定未命中模板")
    if not {"abstract", "keywords"} <= set(fields.values()):
        raise ValueError("模板必须绑定摘要和关键词")
    result_doc = parse(parts["word/document.xml"])
    from .quality import clean_and_check
    quality_report, removed_sections = clean_and_check(result_doc, parse(parts["word/styles.xml"]))
    for image_paragraph in result_doc.xpath(".//w:p[.//w:drawing]", namespaces=NS):
        paragraph_property(image_paragraph, "spacing", line="240", lineRule="auto")
        paragraph_property(image_paragraph, "snapToGrid", val="0")
    parts["word/document.xml"] = xml(result_doc)
    if re.search(r"\{\{[^}]+\}\}|\[\[REF_", text(result_doc)):
        raise ValueError("成稿存在未解析占位符")
    bookmarks = result_doc.xpath(".//w:bookmarkStart/@w:name", namespaces=NS)
    for target in result_doc.xpath(".//w:fldSimple/@w:instr", namespaces=NS):
        if target.startswith("REF Paper") and target.split()[1] not in bookmarks:
            raise ValueError("装配交叉引用目标缺失")
    has_toc = any(re.match(r"\s*TOC\b", instruction) for instruction in result_doc.xpath(
        ".//w:instrText/text()|.//w:fldSimple/@w:instr", namespaces=NS))
    update_fields = (has_toc or bool(quality_report.get("toc_entries"))) and "word/settings.xml" in parts
    if update_fields:
        settings = parse(parts["word/settings.xml"])
        update = settings.find("w:updateFields", NS)
        if update is None:
            update = E.SubElement(settings, "{" + W + "}updateFields")
        update.set("{" + W + "}val", "true")
        parts["word/settings.xml"] = xml(settings)
        for field in result_doc.xpath(".//w:fldChar[@w:fldCharType='begin']|.//w:fldSimple", namespaces=NS):
            field.set("{" + W + "}dirty", "true")
        parts["word/document.xml"] = xml(result_doc)
    # 逐部件证明：styles/theme/fonts/numbering 等二进制相同；sectPr 结构不变。
    changed_parts = [n for n in before if parts[n] != before[n]]
    allowed = {"word/document.xml", rel_name, "[Content_Types].xml"}
    if update_fields:
        old_settings, new_settings = parse(before["word/settings.xml"]), parse(parts["word/settings.xml"])
        for tree in (old_settings, new_settings):
            for node in tree.findall("w:updateFields", NS):
                tree.remove(node)
        if E.tostring(old_settings) != E.tostring(new_settings):
            raise ValueError("域更新开关之外的文档设置发生变化")
        allowed.add("word/settings.xml")
    for name in changed_parts:
        if name not in allowed and not re.fullmatch(r"word/(header|footer)\d+\.xml", name):
            raise ValueError(f"装配修改了受保护部件：{name}")
        if re.fullmatch(r"word/(header|footer)\d+\.xml", name):
            old, new = parse(before[name]), parse(parts[name])
            for tree in (old, new):
                for t in tree.xpath(".//w:t", namespaces=NS):
                    t.text = ""; t.attrib.pop(XML_SPACE, None)
            if E.tostring(old) != E.tostring(new):
                raise ValueError("页眉页脚格式发生改变")
    sections_before = parse(before["word/document.xml"]).xpath(".//w:sectPr", namespaces=NS)
    sections_after = result_doc.xpath(".//w:sectPr", namespaces=NS)
    if [E.tostring(x) for x in sections_before if E.tostring(x) not in removed_sections] != [E.tostring(x) for x in sections_after]:
        raise ValueError("分节格式发生变化")
    report = {"structure_check": quality_report, "template_sha256": fingerprint, "sections": len(records), "assets": len(assets),
              "changed_parts": changed_parts, "added_media": added_media,
              "protected_parts_identical": True, "section_properties_identical": not bool(removed_sections), "retained_section_properties_identical": True,
              "template_format_preserved": True,
              "update_fields_on_open": update_fields,
              "content_sha256": sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    return archive_bytes(parts), report


def asset_constraints(state):
    """传递模板宽度/版心限制；固定图片框需显式选择 fixed。"""
    contract = state.get("assembly_contract")
    if not contract:
        return {}
    template = Path(state.get("new_template_path") or state.get("raw_doc_path", ""))
    if sha256(template.read_bytes()).hexdigest() != contract.get("template_sha256"):
        raise ValueError("模板指纹与装配绑定不一致")
    result = {"table_columns": [int(n) for n in contract.get("tables", {})], "diagram_palette": "black_white"}
    marker = contract.get("paragraphs", {}).get("figure")
    if marker:
        body = parse(package(template)["word/document.xml"]).find("w:body", NS)
        matches = [p for p in body.findall("w:p", NS) if text(p) == marker]
        if len(matches) != 1:
            raise ValueError("图片原型必须唯一")
        extents = matches[0].xpath(".//wp:extent", namespaces=NS)
        if len(extents) != 1:
            raise ValueError("图片原型缺少唯一显示尺寸")
        width, height = int(extents[0].get("cx")), int(extents[0].get("cy"))
        if min(width, height) <= 0:
            raise ValueError("图片原型尺寸无效")
        policy = contract.get("image_sizing", "fit_width")
        if policy not in {"fixed", "fit_width"}:
            raise ValueError("无效图片尺寸策略")
        result["image_sizing"] = policy
        if policy == "fixed":
            result["image_aspect_ratio"] = width / height
        else:
            result["image_max_width_emu"] = width
            # 正文锚点所属节的页面属性在其后的第一个 sectPr 中。
            children = list(body)
            anchor = next((p for p in children if text(p) == contract.get("body_marker")), None)
            if anchor is not None:
                for child in children[children.index(anchor):]:
                    sections = [child] if child.tag == "{" + NS["w"] + "}sectPr" else child.findall(".//w:sectPr", NS)
                    if not sections:
                        continue
                    section = sections[0]
                    page, margins = section.find("w:pgSz", NS), section.find("w:pgMar", NS)
                    if page is not None and margins is not None:
                        def value(node, name):
                            return int(node.get("{" + NS["w"] + "}" + name, "0"))
                        usable_width = value(page, "w") - value(margins, "left") - value(margins, "right")
                        usable_height = value(page, "h") - value(margins, "top") - value(margins, "bottom")
                        if min(usable_width, usable_height) > 0:
                            result["image_max_width_emu"] = min(width, usable_width * 635)
                            # 留出图题空间，超高图片整体等比缩小。
                            result["image_max_height_emu"] = round(usable_height * 635 * 0.9)
                    break
    return result
