# -*- coding: utf-8 -*-
"""
创建 作业.docx
- 按《学术排版核心参数基线》定义 标题1/2/3、正文(Normal)、表格文字 样式
- 清空默认模板遗留的不合规样式属性（蓝色标题、Calibri、西文默认字体等）
- 写入正文段落："这是一份要写的实验报告"
"""
import os
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import Pt, Cm, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "作业.docx")
OUT = os.path.abspath(OUT)

CN_BODY, CN_HEAD, EN = "宋体", "黑体", "Times New Roman"


# ---------------------------------------------------------------- 基础工具
def set_fonts(style, cn_font, en_font=EN):
    """同时锁定西文(ascii/hAnsi)、复杂文本(cs)与中文字体(eastAsia)"""
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), en_font)
    rfonts.set(qn("w:hAnsi"), en_font)
    rfonts.set(qn("w:cs"), en_font)
    rfonts.set(qn("w:eastAsia"), cn_font)


# CT_PPr 中 snapToGrid 之后允许出现的兄弟元素（用于合法插入位置）
PPR_AFTER_SNAP = (
    "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
    "w:rPr", "w:sectPr", "w:pPrChange",
)

# CT_PPr 中 w:ind 之后允许出现的兄弟元素
PPR_AFTER_IND = (
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
    "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)


def set_para_format(style, align, line=1.5, before=0, after=0,
                    first_line_chars=0, size_pt=12):
    """行距/段间距/对齐/首行缩进（缩进用 firstLineChars 实现真正的'2字符'）"""
    pf = style.paragraph_format
    pf.alignment = align
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    # 关闭"对齐到网格"，避免中文行距被文档网格改写；须插入到 schema 规定位置
    ppr = style.element.get_or_add_pPr()
    snap = ppr.find(qn("w:snapToGrid"))
    if snap is None:
        snap = OxmlElement("w:snapToGrid")
        ppr.insert_element_before(snap, *PPR_AFTER_SNAP)
    snap.set(qn("w:val"), "0")

    if first_line_chars:
        ind = ppr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            ppr.insert_element_before(ind, *PPR_AFTER_IND)
        ind.set(qn("w:firstLineChars"), str(int(first_line_chars * 100)))
        # 冗余的绝对值回退（2字符 ≈ 2 × 12pt = 24pt = 480 twips）
        ind.set(qn("w:firstLine"), str(int(first_line_chars * size_pt * 20)))


def build_style(doc, name, base="Normal", style_type=WD_STYLE_TYPE.PARAGRAPH):
    styles = doc.styles
    try:
        st = styles[name]
    except KeyError:
        st = styles.add_style(name, style_type)
        st.base_style = styles[base] if base else None
    return st


# ---------------------------------------------------------------- 主流程
doc = Document()

# 1) 清空默认模板遗留内容
for p in list(doc.paragraphs):
    p._element.getparent().remove(p._element)

# 2) 文档默认字体（docDefaults）—— 清洗 Calibri / 等线 等不合规默认值
styles_el = doc.styles.element
dd = styles_el.find(qn("w:docDefaults"))
if dd is not None:
    rpr_dd = dd.find(qn("w:rPrDefault"))
    if rpr_dd is not None:
        rpr = rpr_dd.find(qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            rpr_dd.append(rpr)
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for attr, val in (("w:ascii", EN), ("w:hAnsi", EN), ("w:cs", EN),
                          ("w:eastAsia", CN_BODY)):
            rf.set(qn(attr), val)
        sz = rpr.find(qn("w:sz"))
        if sz is None:
            sz = OxmlElement("w:sz")
            rpr.append(sz)
        sz.set(qn("w:val"), "24")  # 12pt 小四

# 3) 正文 Normal：宋体/TNR 12pt 两端对齐 1.5倍行距 首行缩进2字符
normal = doc.styles["Normal"]
set_fonts(normal, CN_BODY)
normal.font.size = Pt(12)
normal.font.bold = False
normal.font.color.rgb = RGBColor(0, 0, 0)
set_para_format(normal, WD_ALIGN_PARAGRAPH.JUSTIFY, 1.5, 0, 0, 2, 12)
normal.element.get_or_add_pPr()  # 确保 pPr 存在

# 4) 三级标题样式（供后续内容 Agent 继承）
specs = [
    ("Heading 1", CN_HEAD, 16, True, WD_ALIGN_PARAGRAPH.CENTER, 1.5, 12, 6, 0),
    ("Heading 2", CN_HEAD, 14, True, WD_ALIGN_PARAGRAPH.LEFT, 1.5, 6, 3, 0),
    ("Heading 3", CN_BODY, 12, True, WD_ALIGN_PARAGRAPH.LEFT, 1.5, 3, 0, 0),
]
for name, cn, size, bold, align, line, before, after, indent in specs:
    st = doc.styles[name]
    st.base_style = doc.styles["Normal"]
    set_fonts(st, cn)
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.color.rgb = RGBColor(0, 0, 0)   # 清除 Word 默认蓝色标题
    # 清除默认的海蓝色主题色与斜体残留
    st.font.italic = False
    ppr = st.element.get_or_add_pPr()
    for tag in ("w:numPr",):                # 去掉内置标题的自动编号
        el = ppr.find(qn(tag))
        if el is not None:
            ppr.remove(el)
    set_para_format(st, align, line, before, after, indent, size)

# 5) 表格文字：宋体/TNR 10.5pt 居中 单倍行距 无缩进
tbl = build_style(doc, "表格文字")
set_fonts(tbl, CN_BODY)
tbl.font.size = Pt(10.5)
tbl.font.bold = False
tbl.font.color.rgb = RGBColor(0, 0, 0)
set_para_format(tbl, WD_ALIGN_PARAGRAPH.CENTER, 1.0, 0, 0, 0, 10.5)

# 6) 页面：A4 + 中国高校常用页边距
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin = sec.bottom_margin = Cm(2.54)
sec.left_margin = Cm(3.17)
sec.right_margin = Cm(2.54)

# 7) 写入正文内容
p = doc.add_paragraph("这是一份要写的实验报告", style="Normal")
p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
# 段落级再次锁定中文字体，防止渲染器回退
r = p.runs[0]
r.font.name = EN
r.font.size = Pt(12)
r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), CN_BODY)

doc.save(OUT)
print("已生成:", OUT)
