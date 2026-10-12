# -*- coding: utf-8 -*-
"""生成产物合规性校验: 逐条比对样式参数与三线表边框。"""
import zipfile
import re
from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PATH = "test/academic_template_demo.docx"

z = zipfile.ZipFile(PATH)
styles_xml = z.read("word/styles.xml")
doc_xml = z.read("word/document.xml")
sroot = etree.fromstring(styles_xml)
droot = etree.fromstring(doc_xml)


def q(t):
    return W + t


def dump_style(sid):
    for st in sroot.iter(q("style")):
        if st.get(q("styleId")) == sid:
            name = st.find(q("name")).get(q("val"))
            ppr = st.find(q("pPr"))
            rpr = st.find(q("rPr"))
            rf = rpr.find(q("rFonts")) if rpr is not None else None
            sz = rpr.find(q("sz")) if rpr is not None else None
            b = rpr.find(q("b")) if rpr is not None else None
            col = rpr.find(q("color")) if rpr is not None else None
            info = {
                "name": name,
                "eastAsia": rf.get(q("eastAsia")) if rf is not None else None,
                "ascii": rf.get(q("ascii")) if rf is not None else None,
                "size_pt": (int(sz.get(q("val"))) / 2) if sz is not None else None,
                "bold": (b is not None and b.get(q("val")) in (None, "1", "true")),
                "color": col.get(q("val")) if col is not None else None,
                "jc": ppr.find(q("jc")).get(q("val")) if ppr is not None and ppr.find(q("jc")) is not None else None,
                "spacing": None,
                "ind": None,
            }
            sp = ppr.find(q("spacing")) if ppr is not None else None
            if sp is not None:
                info["spacing"] = {
                    "line": sp.get(q("line")), "lineRule": sp.get(q("lineRule")),
                    "before": sp.get(q("before")), "after": sp.get(q("after")),
                }
            ind = ppr.find(q("ind")) if ppr is not None else None
            if ind is not None:
                info["ind"] = dict(ind.attrib)
                info["ind"] = {k.split('}')[-1]: v for k, v in info["ind"].items()}
            return info
    return None


print("=" * 78)
print("【样式参数校验】")
print("=" * 78)
for sid, label in [("Heading1", "标题1"), ("Heading2", "标题2"),
                   ("Heading3", "标题3"), ("Normal", "正文"), ("TableText", "表格文字")]:
    d = dump_style(sid)
    print(f"\n>>> {label}  (styleId={sid})")
    if d is None:
        print("    !! 未找到样式")
        continue
    for k, v in d.items():
        print(f"    {k:12s}: {v}")

print("\n" + "=" * 78)
print("【三线表边框校验】")
print("=" * 78)
tbl = droot.find(".//" + q("tbl"))
tblPr = tbl.find(q("tblPr"))
tb = tblPr.find(q("tblBorders"))
order = ["top", "left", "bottom", "right", "insideH", "insideV"]
print("\n表级边框 (w:tblBorders):")
for tag in order:
    el = tb.find(q(tag))
    if el is None:
        print(f"  {tag:9s}: <缺失>")
    else:
        szv = el.get(q("sz")) or "0"
        line_pt = int(szv) / 8
        flag = ""
        if tag in ("top", "bottom"):
            flag = "  <== 应为 1.5pt" + ("  ✅" if abs(line_pt - 1.5) < 1e-6 else "  ❌")
        elif tag in ("left", "right", "insideH", "insideV"):
            flag = "  <== 应为 无边框" + ("  ✅" if el.get(q("val")) == "none" else "  ❌")
        print(f"  {tag:9s}: val={el.get(q('val')):<6s} sz={szv:<3s} ({line_pt}pt){flag}")

rows = tbl.findall(q("tr"))
print(f"\n行数: {len(rows)} (含表头)")
hdr_bottom = rows[0].findall(".//" + q("tcBorders") + "/" + q("bottom"))
print("列头行单元格下边框 (栏目线):")
if hdr_bottom:
    el = hdr_bottom[0]
    pt = int(el.get(q("sz"))) / 8
    print(f"  val={el.get(q('val'))} sz={el.get(q('sz'))} ({pt}pt)"
          + ("  <== 应为 0.75pt  ✅" if abs(pt - 0.75) < 1e-6 else "  ❌"))
else:
    print("  ❌ 未找到")

last = rows[-1].findall(".//" + q("tcBorders") + "/" + q("bottom"))
print("末行单元格下边框 (底线):")
if last:
    el = last[0]
    pt = int(el.get(q("sz"))) / 8
    print(f"  val={el.get(q('val'))} sz={el.get(q('sz'))} ({pt}pt)"
          + ("  <== 应为 1.5pt  ✅" if abs(pt - 1.5) < 1e-6 else "  ❌"))

# 检查是否存在任何竖线残留
vert = tbl.findall(".//" + q("tcBorders") + "/*")
vnames = set(etree.QName(e).localname for e in vert)
print(f"\n单元格级边框类型: {sorted(vnames)}  (含 left/right 才为违规)")

print("\n" + "=" * 78)
print("【正文段落统计】")
print("=" * 78)
body = droot.find(q("body"))
for p in body.findall(q("p")):
    ppr = p.find(q("pPr"))
    sid = ppr.find(q("pStyle")).get(q("val")) if ppr is not None and ppr.find(q("pStyle")) is not None else "Normal"
    txt = "".join(t.text or "" for t in p.iter(q("t")))
    ind = ppr.find(q("ind")) if ppr is not None else None
    chars = ind.get(q("firstLineChars")) if ind is not None else None
    print(f"  [{sid:10s}] firstLineChars={str(chars):5s} | {txt[:34]}")
