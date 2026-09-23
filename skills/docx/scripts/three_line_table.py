#!/usr/bin/env python3
"""
Three-Line Table (三线表) Helper Script for DOCX Skill.
Applies standard academic Three-Line Table styling to docx tables:
- Top border: 1.5 pt (sz="12")
- Header bottom border: 0.75 pt (sz="6")
- Bottom border: 1.5 pt (sz="12")
- No vertical or inner horizontal borders.

Usage:
  python scripts/three_line_table.py input.docx -o output.docx [--color 1A365D]
  python scripts/three_line_table.py input.docx (overwrites input.docx in-place)
"""

import sys
import argparse
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def apply_three_line_style(table, color="000000", top_sz=12, header_bottom_sz=6, bottom_sz=12):
    """Format a python-docx Table object as a standard Three-Line Table."""
    # 1. Clear & set Table-level borders to 'none' so default grid lines are hidden
    tblPr = table._tbl.tblPr
    tblBorders = tblPr.first_child_found_in("w:tblBorders")
    if tblBorders is None:
        tblBorders = OxmlElement('w:tblBorders')
        tblPr.append(tblBorders)
    else:
        tblBorders.clear()

    for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        el = OxmlElement(f'w:{border_name}')
        el.set(qn('w:val'), 'none')
        el.set(qn('w:sz'), '0')
        el.set(qn('w:color'), 'auto')
        tblBorders.append(el)

    rows = table.rows
    if not rows:
        return

    # 2. Format Header Row (Row 0)
    for cell in rows[0].cells:
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = tcPr.first_child_found_in("w:tcBorders")
        if tcBorders is None:
            tcBorders = OxmlElement('w:tcBorders')
            tcPr.append(tcBorders)
        else:
            tcBorders.clear()

        # Top border (1.5pt)
        top_el = OxmlElement('w:top')
        top_el.set(qn('w:val'), 'single')
        top_el.set(qn('w:sz'), str(top_sz))
        top_el.set(qn('w:color'), color)
        tcBorders.append(top_el)

        # Header Bottom border (0.75pt)
        bot_el = OxmlElement('w:bottom')
        bot_el.set(qn('w:val'), 'single')
        bot_el.set(qn('w:sz'), str(header_bottom_sz))
        bot_el.set(qn('w:color'), color)
        tcBorders.append(bot_el)

        # Left / Right = none
        for side in ['left', 'right']:
            side_el = OxmlElement(f'w:{side}')
            side_el.set(qn('w:val'), 'none')
            tcBorders.append(side_el)

    # 3. Format Data Rows (Middle Rows: no borders)
    for row in rows[1:-1]:
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = tcPr.first_child_found_in("w:tcBorders")
            if tcBorders is None:
                tcBorders = OxmlElement('w:tcBorders')
                tcPr.append(tcBorders)
            else:
                tcBorders.clear()

            for side in ['top', 'bottom', 'left', 'right']:
                side_el = OxmlElement(f'w:{side}')
                side_el.set(qn('w:val'), 'none')
                tcBorders.append(side_el)

    # 4. Format Bottom Row (Last Row: bottom 1.5pt)
    if len(rows) > 1:
        for cell in rows[-1].cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = tcPr.first_child_found_in("w:tcBorders")
            if tcBorders is None:
                tcBorders = OxmlElement('w:tcBorders')
                tcPr.append(tcBorders)
            else:
                tcBorders.clear()

            bot_el = OxmlElement('w:bottom')
            bot_el.set(qn('w:val'), 'single')
            bot_el.set(qn('w:sz'), str(bottom_sz))
            bot_el.set(qn('w:color'), color)
            tcBorders.append(bot_el)

            for side in ['top', 'left', 'right']:
                side_el = OxmlElement(f'w:{side}')
                side_el.set(qn('w:val'), 'none')
                tcBorders.append(side_el)


def process_docx(input_file, output_file, color="000000"):
    doc = Document(input_file)
    count = 0
    for table in doc.tables:
        apply_three_line_style(table, color=color)
        count += 1
    
    doc.save(output_file)
    print(f"Successfully formatted {count} table(s) in '{input_file}' to Three-Line Table style -> '{output_file}'.")


def main():
    parser = argparse.ArgumentParser(description="Convert docx tables to standard Three-Line Table style.")
    parser.add_argument("input", help="Input .docx file path")
    parser.add_argument("-o", "--output", help="Output .docx file path (defaults to overwriting input)")
    parser.add_argument("--color", default="000000", help="Border color in hex (default: 000000)")
    
    args = parser.parse_args()
    out_path = args.output if args.output else args.input
    process_docx(args.input, out_path, color=args.color)

if __name__ == "__main__":
    main()
