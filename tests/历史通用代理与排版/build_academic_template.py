# -*- coding: utf-8 -*-
"""
中国高校本科毕业设计 Word 模板 —— 标准化排版引擎
=================================================
功能:
  1. 创建全新空白 .docx
  2. 清空/覆盖默认不合规样式, 精准定义 5 种标准样式:
     Heading 1 / Heading 2 / Heading 3 / Normal(正文) / 表格文字(Table)
  3. 构建符合中国学术规范的三线表 (顶线底线 1.5pt, 栏目线 0.75pt, 无竖线)
  4. 填充示范内容并导出

作者: DocxTemplateAgent (Agent 1)
"""

import os
import sys

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# ----------------------------------------------------------------------------
# 常量基线
# ----------------------------------------------------------------------------
CN_HEI = "黑体"
CN_SONG = "宋体"
EN_FONT = "Times New Roman"
BLACK = RGBColor(0x00, 0x00, 0x00)

OUTPUT_PATH = os.path.join("test", "academic_template_demo.docx")

# 线宽: w:sz 单位为 1/8 pt
SZ_1_5PT = 12   # 1.5pt 粗线
SZ_0_75PT = 6   # 0.75pt 细线


# ----------------------------------------------------------------------------
# 底层 OpenXML 工具函数
# ----------------------------------------------------------------------------
def _kill_theme_fonts(rfonts):
    """移除主题字体引用, 防止 rFonts 主题属性覆盖显式字体设定。"""
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rfonts.get(qn(attr)) is not None:
            del rfonts.attrib[qn(attr)]


def set_run_fonts(rpr, cn_font, en_font):
    """在指定的 <w:rPr> 上锁定中西文字体。"""
    rfonts = rpr.get_or_add_rFonts()
    _kill_theme_fonts(rfonts)
    rfonts.set(qn("w:ascii"), en_font)
    rfonts.set(qn("w:hAnsi"), en_font)
    rfonts.set(qn("w:eastAsia"), cn_font)
    rfonts.set(qn("w:cs"), en_font)
    rfonts.set(qn("w:hint"), "eastAsia")
    return rfonts


def style_set_fonts(style, cn_font, en_font):
    """为段落/字符样式锁定中西文字体 (样式级)。"""
    rpr = style.element.get_or_add_rPr()
    set_run_fonts(rpr, cn_font, en_font)


def set_first_line_chars(pf, chars_twips_hundredths, indent_pt):
    """
    设置首行缩进:
      - indent_pt  : 绝对磅值缩进 (兼容不支持字符缩进的渲染器)
      - chars      : w:firstLineChars, 单位为 1/100 字符 (200 == 2 字符)
    """
    pf.first_line_indent = Pt(indent_pt)          # 创建 w:ind 于正确位置
    ppr = pf._element.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    if ind is None:                               # 理论上不会发生
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    if chars_twips_hundredths:
        ind.set(qn("w:firstLineChars"), str(chars_twips_hundredths))
    else:
        # 清除字符缩进, 保证标题等无缩进
        if ind.get(qn("w:firstLineChars")) is not None:
            del ind.attrib[qn("w:firstLineChars")]


def set_doc_default_fonts(doc, cn_font, en_font, size_pt):
    """写入 styles.xml/docDefaults, 保证未显式指定样式时字体亦合规。"""
    styles_el = doc.styles.element
    rprd = styles_el.find(qn("w:docDefaults")).find(qn("w:rPrDefault"))
    rpr = rprd.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        rprd.append(rpr)
    set_run_fonts(rpr, cn_font, en_font)
    sz = rpr.find(qn("w:sz"))
    if sz is None:
        sz = OxmlElement("w:sz")
        rpr.append(sz)
    sz.set(qn("w:val"), str(int(size_pt * 2)))


# ----------------------------------------------------------------------------
# 三线表边框工具
# ----------------------------------------------------------------------------
def _border_el(tag, sz_eighth_pt, val="single", color="000000"):
    el = OxmlElement("w:" + tag)
    el.set(qn("w:val"), val)
    el.set(qn("w:sz"), str(sz_eighth_pt))
    el.set(qn("w:space"), "0")
    el.set(qn("w:color"), color)
    return el


def apply_three_line_table_borders(table, top_sz=SZ_1_5PT, bottom_sz=SZ_1_5PT,
                                   header_sz=SZ_0_75PT, color="000000"):
    """
    表格级边框:
      top     = 1.5pt 单黑线  (顶线)
      bottom  = 1.5pt 单黑线  (底线)
      left/right/insideH/insideV = 无 (去除全部竖线与表内横线)
    列头行底部再补 0.75pt 栏目线。
    """
    tbl_pr = table._tbl.tblPr
    for old in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(old)

    borders = OxmlElement("w:tblBorders")
    borders.append(_border_el("top", top_sz, "single", color))
    borders.append(_border_el("left", 0, "none", color))
    borders.append(_border_el("bottom", bottom_sz, "single", color))
    borders.append(_border_el("right", 0, "none", color))
    borders.append(_border_el("insideH", 0, "none", color))
    borders.append(_border_el("insideV", 0, "none", color))

    # 依据 CT_TblPr 的 schema 顺序插入
    tbl_pr.insert_element_before(
        borders,
        "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
        "w:tblCaption", "w:tblDescription", "w:tblPrChange",
    )

    # 栏目线: 列头行单元格下边框 0.75pt
    for cell in table.rows[0].cells:
        tc_pr = cell._tc.get_or_add_tcPr()
        for old in tc_pr.findall(qn("w:tcBorders")):
            tc_pr.remove(old)
        tcb = OxmlElement("w:tcBorders")
        tcb.append(_border_el("bottom", header_sz, "single", color))
        tc_pr.insert_element_before(
            tcb,
            "w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
            "w:tcFitText", "w:vAlign", "w:hideMark",
        )

    # 底线: 末行单元格下边框 1.5pt (显式加固)
    for cell in table.rows[-1].cells:
        tc_pr = cell._tc.get_or_add_tcPr()
        tcb = tc_pr.find(qn("w:tcBorders"))
        if tcb is None:
            tcb = OxmlElement("w:tcBorders")
            tc_pr.insert_element_before(
                tcb,
                "w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
                "w:tcFitText", "w:vAlign", "w:hideMark",
            )
        bottom = tcb.find(qn("w:bottom"))
        if bottom is None:
            bottom = OxmlElement("w:bottom")
            tcb.append(bottom)
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), str(bottom_sz))
        bottom.set(qn("w:space"), "0")
        bottom.set(qn("w:color"), color)

    # 表头跨页重复
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:tblHeader")) is None:
        tr_pr.append(OxmlElement("w:tblHeader"))


def keep_table_together(table, caption_para=None):
    """
    保证表格整体不被分页截断:
      - 表题段落 keepNext
      - 每一行加 <w:cantSplit> (禁止行内跨页断开)
      - 除末行外所有单元格段落 keepNext (使各行粘合为整体)
    """
    if caption_para is not None:
        caption_para.paragraph_format.keep_with_next = True

    rows = table.rows
    last = len(rows) - 1
    for i, row in enumerate(rows):
        tr_pr = row._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:cantSplit")) is None:
            cant = OxmlElement("w:cantSplit")
            tr_pr.insert_element_before(
                cant, "w:trHeight", "w:tblHeader", "w:tblCellSpacing",
                "w:jc", "w:hidden",
            )
        if i < last:
            for cell in row.cells:
                for para in cell.paragraphs:
                    para.paragraph_format.keep_with_next = True


def set_cell_margins(table, top=40, bottom=40, left=80, right=80):
    """单元格内边距 (单位: dxa, 20 dxa = 1pt)。"""
    tbl_pr = table._tbl.tblPr
    for old in tbl_pr.findall(qn("w:tblCellMar")):
        tbl_pr.remove(old)
    mar = OxmlElement("w:tblCellMar")
    for tag, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement("w:" + tag)
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tbl_pr.insert_element_before(
        mar, "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange"
    )


# ----------------------------------------------------------------------------
# 样式配置
# ----------------------------------------------------------------------------
def configure_style(style, cn_font, en_font, size_pt, bold,
                    align, line_spacing, space_before, space_after,
                    first_line_pt, first_line_chars):
    """统一配置一个段落样式的字体/对齐/行距/间距/缩进。"""
    style.element.get_or_add_pPr()  # 确保 pPr 存在

    # --- 字体 ---
    style_set_fonts(style, cn_font, en_font)
    style.font.name = en_font                    # 显式西文名
    style.font.size = Pt(size_pt)
    style.font.bold = bold
    style.font.color.rgb = BLACK

    # --- 段落 ---
    pf = style.paragraph_format
    pf.alignment = align
    pf.line_spacing = line_spacing
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.first_line_indent = Pt(first_line_pt)
    set_first_line_chars(pf, first_line_chars, first_line_pt)

    # 关闭网格对齐, 避免行距被文档网格压缩
    ppr = style.element.get_or_add_pPr()
    snap = ppr.find(qn("w:snapToGrid"))
    if snap is None:
        snap = OxmlElement("w:snapToGrid")
        ppr.insert_element_before(
            snap, "w:spacing", "w:ind", "w:contextualSpacing", "w:jc",
            "w:textAlignment", "w:outlineLvl", "w:rPr",
        )
    snap.set(qn("w:val"), "0")
    return style


def build_template():
    doc = Document()

    # ===== 1. 页面设置 (A4, 学位论文常用页边距) =====
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.54)
    sec.bottom_margin = Cm(2.54)
    sec.left_margin = Cm(3.0)
    sec.right_margin = Cm(2.6)
    sec.header_distance = Cm(1.5)
    sec.footer_distance = Cm(1.75)
    content_width_cm = 21.0 - 3.0 - 2.6          # = 15.4 cm

    # ===== 2. 全局默认字体 =====
    set_doc_default_fonts(doc, CN_SONG, EN_FONT, 12)

    # ===== 3. 清空/覆盖默认样式 =====
    styles = doc.styles

    # 3.1 正文 Normal —— 宋体 / TNR 12pt / 两端对齐 / 1.5倍 / 首行缩进2字符
    normal = styles["Normal"]
    configure_style(
        normal, CN_SONG, EN_FONT, 12, False,
        WD_ALIGN_PARAGRAPH.JUSTIFY, 1.5, 0, 0,
        first_line_pt=24, first_line_chars=200,
    )

    # 3.2 标题 1 —— 黑体 / TNR 16pt 加粗 / 居中 / 1.5倍 / 段前12 段后6
    h1 = styles["Heading 1"]
    configure_style(
        h1, CN_HEI, EN_FONT, 16, True,
        WD_ALIGN_PARAGRAPH.CENTER, 1.5, 12, 6,
        first_line_pt=0, first_line_chars=0,
    )

    # 3.3 标题 2 —— 黑体 / TNR 14pt 加粗 / 居左 / 1.5倍 / 段前6 段后3
    h2 = styles["Heading 2"]
    configure_style(
        h2, CN_HEI, EN_FONT, 14, True,
        WD_ALIGN_PARAGRAPH.LEFT, 1.5, 6, 3,
        first_line_pt=0, first_line_chars=0,
    )

    # 3.4 标题 3 —— 宋体 / TNR 12pt 加粗 / 居左 / 1.5倍 / 段前3 段后0
    h3 = styles["Heading 3"]
    configure_style(
        h3, CN_SONG, EN_FONT, 12, True,
        WD_ALIGN_PARAGRAPH.LEFT, 1.5, 3, 0,
        first_line_pt=0, first_line_chars=0,
    )

    # 3.5 表格文字 (Table) —— 宋体 / TNR 10.5pt / 居中 / 单倍行距
    if "表格文字" in [s.name for s in styles]:
        table_style = styles["表格文字"]
    else:
        table_style = styles.add_style("表格文字", WD_STYLE_TYPE.PARAGRAPH)
        table_style.element.set(qn("w:styleId"), "TableText")
        table_style.base_style = styles["Normal"]
        table_style.quick_style = True
    configure_style(
        table_style, CN_SONG, EN_FONT, 10.5, False,
        WD_ALIGN_PARAGRAPH.CENTER, 1.0, 0, 0,
        first_line_pt=0, first_line_chars=0,
    )

    # ===== 4. 示范内容 =====
    _fill_demo_content(doc, content_width_cm)

    # ===== 5. 页脚页码 =====
    _add_page_number_footer(sec)

    # ===== 6. 保存 =====
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    doc.save(OUTPUT_PATH)
    return OUTPUT_PATH


def _p(doc, text, style=None):
    p = doc.add_paragraph(text)
    if style:
        p.style = style
    return p


def _fill_demo_content(doc, content_width_cm):
    """填充第一章示范内容 + 标准三线表。"""
    styles = doc.styles

    # ---- 标题 1 ----
    _p(doc, "1 绪论", styles["Heading 1"])

    # ---- 标题 2 ----
    _p(doc, "1.1 研究背景与意义", styles["Heading 2"])

    # ---- 标题 3 ----
    _p(doc, "1.1.1 现实痛点分析", styles["Heading 3"])

    body_texts = [
        "近年来，随着高等教育规模的持续扩大以及社会竞争压力的不断加剧，高校学生的心理健康问题日益凸显，已成为"
        "影响人才培养质量与校园安全稳定的重要因素。据教育部相关统计数据显示，我国普通高等学校在校生规模已突破"
        "四千万人，而专职心理健康教育教师的配备比例长期低于国家规定标准，师生比失衡的矛盾十分突出。传统的以"
        "线下预约、人工登记、纸质档案为核心的心理咨询服务模式，在面对规模化、常态化的心理服务需求时，逐渐暴露"
        "出响应迟缓、资源错配、数据孤岛等结构性缺陷。",

        "从服务流程来看，学生若需接受心理咨询，通常需要前往心理健康教育与咨询中心现场填写纸质申请表，再由值班"
        "教师依据空闲时段人工排期，整个预约周期平均长达三至五日。在此过程中，学生往往因流程繁琐、隐私顾虑或"
        "时间冲突而放弃求助，导致大量潜在的心理危机未能在萌芽阶段被识别与干预。与此同时，咨询记录以纸质档案"
        "形式分散保存，跨部门调阅困难，既不利于个案跟踪，也难以支撑群体性的心理健康态势研判。",

        "因此，设计并实现一套面向高校场景的心理咨询信息化管理系统，通过在线预约、标准化测评、电子档案与智能"
        "预警等功能模块的有机集成，对于提升心理服务的可及性、规范性与科学性具有重要的现实意义。本课题正是在"
        "这一背景下展开，旨在探索信息技术与高校心理健康教育工作深度融合的可行路径。",
    ]
    for t in body_texts:
        _p(doc, t, styles["Normal"])

    # ---- 三级标题: 表前小节 ----
    _p(doc, "1.1.2 核心功能需求对比", styles["Heading 3"])

    _p(doc,
       "为明确系统设计目标，本文对传统线下服务模式与本课题所提系统方案在核心功能维度上的差异进行了系统梳理，"
       "对比结果如表 1-1 所示。",
       styles["Normal"])

    # ---- 表题 (居中、无缩进、五号) ----
    caption = doc.add_paragraph("表 1-1  高校心理咨询系统核心功能需求对比表")
    caption.style = styles["表格文字"]
    caption.paragraph_format.space_before = Pt(6)
    caption.paragraph_format.space_after = Pt(3)
    # 表题中文字体使用黑体更符合规范
    for run in caption.runs:
        set_run_fonts(run._element.get_or_add_rPr(), CN_HEI, EN_FONT)

    # ---- 标准三线表 ----
    headers = ["功能模块", "传统线下模式", "本系统设计方案", "效率提升"]
    rows_data = [
        ["预约排期", "现场登记排队，平均等待 3 天", "在线自主预约，实时智能排期", "约 90%"],
        ["心理测评", "纸质问卷发放，人工计分", "标准化量表在线作答并自动计分", "约 85%"],
        ["档案管理", "纸质档案分散存放，检索困难", "加密电子档案，分级权限管控", "约 80%"],
        ["危机预警", "依赖人工发现，响应滞后", "多维度数据建模，自动触发预警", "约 75%"],
    ]
    col_widths_cm = [2.9, 4.6, 5.3, 2.6]          # 合计 15.4 cm
    assert abs(sum(col_widths_cm) - content_width_cm) < 0.05

    table = doc.add_table(rows=1 + len(rows_data), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # 清除可能的表格样式, 避免默认网格线
    tbl_pr = table._tbl.tblPr
    for ts in tbl_pr.findall(qn("w:tblStyle")):
        tbl_pr.remove(ts)

    # 列宽 (表级 + 单元格级双写)
    for i, w in enumerate(col_widths_cm):
        for row in table.rows:
            row.cells[i].width = Cm(w)

    # 表头
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        para = cell.paragraphs[0]
        para.style = styles["表格文字"]
        run = para.add_run(h)
        run.bold = True
        set_run_fonts(run._element.get_or_add_rPr(), CN_HEI, EN_FONT)

    # 数据行
    for r, data in enumerate(rows_data, start=1):
        for c, val in enumerate(data):
            cell = table.rows[r].cells[c]
            cell.text = ""
            para = cell.paragraphs[0]
            para.style = styles["表格文字"]
            para.add_run(val)

    # 垂直居中
    for row in table.rows:
        for cell in row.cells:
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    set_cell_margins(table)
    apply_three_line_table_borders(table)

    # ---- 保证整张表落在同一页 ----
    keep_table_together(table, caption_para=caption)

    # ---- 表注 ----
    note = doc.add_paragraph("注：效率提升数据来源于 2024 年 3—5 月对本校 320 名在校学生的问卷调研与业务流程模拟测算。")
    note.style = styles["表格文字"]
    note.paragraph_format.space_before = Pt(3)
    note.paragraph_format.space_after = Pt(6)
    for run in note.runs:
        run.font.size = Pt(9)


def _add_page_number_footer(section):
    """页脚居中插入页码域 (PAGE)。"""
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_p.paragraph_format.first_line_indent = Pt(0)
    if footer_p.paragraph_format._element.find(qn("w:pPr")) is not None:
        ind = footer_p.paragraph_format._element.find(qn("w:pPr")).find(qn("w:ind"))
        if ind is not None:
            footer_p.paragraph_format._element.find(qn("w:pPr")).remove(ind)

    run = footer_p.add_run()
    run.font.size = Pt(10.5)
    set_run_fonts(run._element.get_or_add_rPr(), CN_SONG, EN_FONT)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._element.append(fld_begin)
    run._element.append(instr)
    run._element.append(fld_end)


if __name__ == "__main__":
    path = build_template()
    print("[OK] 文档已生成:", os.path.abspath(path))
