# -*- coding: utf-8 -*-
"""从渲染后的 PDF 中提取矢量绘图, 反推三线表的实际线宽是否符合规范。"""
import pymupdf

doc = pymupdf.open("test/academic_template_demo.pdf")
out = []

for pno, page in enumerate(doc, start=1):
    out.append("=" * 70)
    out.append("PAGE %d" % pno)
    out.append("=" * 70)
    drawings = page.get_drawings()
    horiz = []   # (y, x0, x1, width_pt)
    vert = []    # (x, y0, y1, width_pt)
    other = 0
    for d in drawings:
        w = d.get("width") or 0
        for item in d["items"]:
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 0.6:
                    horiz.append((round(p1.y, 2), round(min(p1.x, p2.x), 2),
                                  round(max(p1.x, p2.x), 2), round(w, 3)))
                elif abs(p1.x - p2.x) < 0.6:
                    vert.append((round(p1.x, 2), round(min(p1.y, p2.y), 2),
                                 round(max(p1.y, p2.y), 2), round(w, 3)))
                else:
                    other += 1
            elif op == "re":
                r = item[1]
                if r.width > r.height:
                    horiz.append((round(r.y0, 2), round(r.x0, 2), round(r.x1, 2),
                                  round(r.height, 3)))
                else:
                    vert.append((round(r.x0, 2), round(r.y0, 2), round(r.y1, 2),
                                 round(r.width, 3)))

    out.append("")
    out.append("--- 水平线 (y, x_start, x_end, 线宽pt) --- 共 %d 条" % len(horiz))
    for h in sorted(horiz):
        if h[2] - h[1] > 100:      # 仅关注表格长横线
            out.append("  y=%-8s x:%-8s -> %-8s  线宽=%.3f pt" % (h[0], h[1], h[2], h[3]))
    out.append("")
    out.append("--- 竖线 (x, y_start, y_end, 线宽pt) --- 共 %d 条" % len(vert))
    for v in sorted(vert):
        if v[2] - v[1] > 5:
            out.append("  x=%-8s y:%-8s -> %-8s  线宽=%.3f pt" % (v[0], v[1], v[2], v[3]))
    if not [v for v in vert if v[2] - v[1] > 5]:
        out.append("  (无竖线 —— 符合三线表规范)")

open("test/render/borders.txt", "w", encoding="utf-8").write("\n".join(out))
print("done")
