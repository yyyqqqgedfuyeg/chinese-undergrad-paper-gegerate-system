# -*- coding: utf-8 -*-
"""检查 作业.docx 的样式参数、页面设置、内容与 OpenXML 细节"""
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

DOC = "作业.docx"
d = Document(DOC)

print("=== 正文内容 ===")
for i, p in enumerate(d.paragraphs):
    runs = [(r.text, r.font.name, r.font.size.pt if r.font.size else None,
             (r._element.rPr.rFonts.get(qn("w:eastAsia")) if r._element.rPr is not None
              and r._element.rPr.rFonts is not None else None)) for r in p.runs]
    print(f"  [{i}] {p.text!r} 样式={p.style.name} 运行={runs}")

print("\n=== 样式参数核查 ===")
for n in ["Normal", "Heading 1", "Heading 2", "Heading 3", "表格文字"]:
    s = d.styles[n]
    pf = s.paragraph_format
    rpr = s.element.find(qn("w:rPr"))
    rf = rpr.find(qn("w:rFonts"))
    ppr = s.element.find(qn("w:pPr"))
    ind = ppr.find(qn("w:ind")) if ppr is not None else None
    snap = ppr.find(qn("w:snapToGrid")) if ppr is not None else None
    print(
        f"  [{n}] 中文字体={rf.get(qn('w:eastAsia'))} 西文字体={rf.get(qn('w:ascii'))} "
        f"字号={s.font.size.pt if s.font.size else None}pt 加粗={s.font.bold} "
        f"颜色={s.font.color.rgb} 对齐={pf.alignment} 行距={pf.line_spacing} "
        f"段前={pf.space_before.pt if pf.space_before else 0}pt "
        f"段后={pf.space_after.pt if pf.space_after else 0}pt "
        f"firstLineChars={ind.get(qn('w:firstLineChars')) if ind is not None else None} "
        f"snapToGrid={snap.get(qn('w:val')) if snap is not None else None}"
    )

print("\n=== 页面设置 ===")
sec = d.sections[0]
print(f"  页面 {sec.page_width.cm:.2f} x {sec.page_height.cm:.2f} cm | "
      f"上{sec.top_margin.cm:.2f} 下{sec.bottom_margin.cm:.2f} "
      f"左{sec.left_margin.cm:.2f} 右{sec.right_margin.cm:.2f} cm")

print("\n=== OpenXML 细节 ===")
z = zipfile.ZipFile(DOC)
s = z.read("word/settings.xml").decode("utf-8")
m = re.search(r"<w:zoom[^>]*/?>", s)
print("  settings zoom:", m.group(0) if m else "NONE")
st = z.read("word/styles.xml").decode("utf-8")
for mm in re.finditer(r"<w:pPr>.*?</w:pPr>", st, re.S):
    if "snapToGrid" in mm.group(0):
        print("  pPr:", mm.group(0))
        break
dd = re.search(r"<w:docDefaults>.*?</w:docDefaults>", st, re.S)
print("  docDefaults:", dd.group(0)[:300] if dd else "NONE")
