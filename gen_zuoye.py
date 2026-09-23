# -*- coding: utf-8 -*-
"""生成 作业.docx —— 符合高校学术排版规范的 Word 文档"""
import os
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn

WS = r"E:\CODING\PYTHON\chinese-undergrad-paper-gegerate-system"
OUT = os.path.join(WS, "作业.docx")


def set_font(run, cn_font, en_font, size_pt, bold=False):
    """同时锁定中西文字体"""
    run.font.name = en_font
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn('w:ascii'), en_font)
    rfonts.set(qn('w:hAnsi'), en_font)
    rfonts.set(qn('w:eastAsia'), cn_font)


def config_normal_style(doc):
    """配置正文 (Normal) 样式: 宋体/Times New Roman 小四 1.5倍行距 首行缩进2字符"""
    st = doc.styles['Normal']
    st.font.name = 'Times New Roman'
    st.font.size = Pt(12)
    rpr = st.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn('w:ascii'), 'Times New Roman')
    rfonts.set(qn('w:hAnsi'), 'Times New Roman')
    rfonts.set(qn('w:eastAsia'), '宋体')

    pf = st.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)


def add_body_paragraph(doc, text):
    """插入正文段落: 首行缩进 2 字符 (24pt)"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.first_line_indent = Pt(24)          # 2 字符 @ 12pt
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    run = p.add_run(text)
    set_font(run, '宋体', 'Times New Roman', 12, bold=False)
    return p


def main():
    doc = Document()

    # 页面设置: A4 + 常规页边距
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.54)
    sec.bottom_margin = Cm(2.54)
    sec.left_margin = Cm(3.17)
    sec.right_margin = Cm(3.17)

    # 配置正文样式
    config_normal_style(doc)

    # 插入正文内容
    add_body_paragraph(doc, "这是一份要写的实验报告。")

    doc.save(OUT)
    print("[OK] 已生成:", OUT, "| 大小:", os.path.getsize(OUT), "bytes")


if __name__ == '__main__':
    main()
