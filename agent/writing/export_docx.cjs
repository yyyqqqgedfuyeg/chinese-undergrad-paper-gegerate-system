/* 基于项目 docx skill 的确定性 DOCX 装配器。 */
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  ImageRun, Bookmark, SimpleField, Footer, Header, PageNumber, LineRuleType,
} = require('docx');

const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = process.argv[3];
const PAGE_WIDTH = 11906, PAGE_HEIGHT = 16838, MARGIN = 1417;
const CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN;
const records = new Map(input.records.map(r => [r.section_id, r]));
const assets = new Map();
const counts = {};
for (const record of input.records) {
  const chapter = record.section_id.split('.')[0];
  for (const asset of record.assets) {
    const kind = asset.kind === 'table' ? '表' : '图';
    const key = `${chapter}-${kind}`;
    counts[key] = (counts[key] || 0) + 1;
    assets.set(asset.asset_id, {...asset, label: `${kind} ${chapter}-${counts[key]}`});
  }
}
const usedCitations = [];
for (const record of input.records) {
  for (const match of record.content.matchAll(/\[\[REF_CITE:([^\]]+)\]\]/g)) {
    if (!usedCitations.includes(match[1])) usedCitations.push(match[1]);
  }
}
const noBorder = {style: BorderStyle.NONE, size: 0, color: 'FFFFFF'};
const font = {ascii: 'Times New Roman', hAnsi: 'Times New Roman', eastAsia: 'Noto Serif CJK SC'};
function inline(text) {
  text = text.replace(/([图表]\s*\d+\s*[-－]\s*\d+)(\s*给出[^。；：\n]{0,12})(\[\[REF_(?:FIG|TABLE):([^\]]+)\]\])/g,
    (whole, label, bridge, marker, id) => assets.get(id)?.label.replace(/\s/g, '') === label.replace(/\s/g, '').replace('－', '-') ? marker + bridge : whole);
  // 模型偶尔在引用锚点前又写一次图表号；避免成稿出现“图2-1图2-1”。
  text = text.replace(/([图表]\s*\d+\s*[-－]\s*\d+)\s*(\[\[REF_(?:FIG|TABLE):([^\]]+)\]\])/g,
    (whole, label, marker, id) => assets.get(id)?.label.replace(/\s/g, '') === label.replace(/\s/g, '').replace('－', '-') ? marker : whole);
  const parts = text.split(/(\[\[REF_(?:FIG|TABLE|CITE):[^\]]+\]\]|\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.filter(Boolean).map(part => {
    const ref = part.match(/^\[\[REF_(FIG|TABLE|CITE):([^\]]+)\]\]$/);
    if (ref) {
      if (ref[1] === 'CITE') return new TextRun({text: `[${usedCitations.indexOf(ref[2]) + 1}]`, superScript: true});
      const asset = assets.get(ref[2]);
      if (!asset) throw new Error(`Unknown asset ${ref[2]}`);
      return new SimpleField(`REF ${ref[2]} \\h`, asset.label);
    }
    if (part.startsWith('**')) return new TextRun({text: part.slice(2, -2), bold: true});
    if (part.startsWith('`')) return new TextRun({text: part.slice(1, -1), font: {ascii: 'DejaVu Sans Mono', eastAsia: 'Noto Sans CJK SC'}, size: 20});
    return new TextRun(part);
  });
}
function body(text) {
  return text.trim().split(/\n\s*\n/).filter(Boolean).map(block => new Paragraph({
    children: inline(block.replace(/^#{1,6}\s+/gm, '').replace(/\n/g, ' ')),
    spacing: {after: 100, line: 360}, indent: {firstLine: 480},
    alignment: AlignmentType.JUSTIFIED, widowControl: true,
  }));
}
function caption(asset) {
  const description = asset.description.replace(/^[图表]\s*\d+\s*[-－]\s*\d+\s*/, '')
    .replace(/（[^）]*）|\([^)]*\)/g, '').split(/[：:]/)[0].trim();
  return new Paragraph({alignment: AlignmentType.CENTER, keepNext: asset.kind === 'table',
    spacing: {before: 120, after: 100}, children: [new Bookmark({id: asset.asset_id,
      children: [new TextRun({text: asset.label, size: 20})]}),
      new TextRun({text: `  ${description}`, size: 20})]});
}
function table(asset) {
  const {columns, rows} = asset.data;
  const widths = columns.map((_, i) => Math.floor(CONTENT_WIDTH / columns.length) +
    (i === columns.length - 1 ? CONTENT_WIDTH % columns.length : 0));
  return new Table({width: {size: CONTENT_WIDTH, type: WidthType.DXA}, columnWidths: widths,
    borders: {top: noBorder, bottom: noBorder, left: noBorder, right: noBorder,
              insideHorizontal: noBorder, insideVertical: noBorder},
    rows: [columns, ...rows].map((row, index) => new TableRow({tableHeader: index === 0, cantSplit: true,
      children: row.map((value, col) => new TableCell({width: {size: widths[col], type: WidthType.DXA},
        margins: {top: 80, bottom: 80, left: 80, right: 80},
        shading: {type: ShadingType.CLEAR, fill: 'FFFFFF'},
        borders: {left: noBorder, right: noBorder,
          top: index === 0 ? {style: BorderStyle.SINGLE, size: 12, color: '111111'} : noBorder,
          bottom: index === 0 ? {style: BorderStyle.SINGLE, size: 6, color: '111111'} :
                  index === rows.length ? {style: BorderStyle.SINGLE, size: 12, color: '111111'} : noBorder},
        children: [new Paragraph({children: [new TextRun({text: value, bold: index === 0, size: 19})],
          spacing: {after: 0, line: 260}, widowControl: true, keepNext: index < rows.length})],
      }))})),
  });
}
function figure(asset) {
  const data = fs.readFileSync(asset.absolute_path);
  let width = 1000, height = 700;
  if (data.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) {
    width = data.readUInt32BE(16); height = data.readUInt32BE(20);
  }
  const scale = Math.min(590 / width, 390 / height);
  const displayWidth = Math.round(width * scale), displayHeight = Math.round(height * scale);
  return new Paragraph({alignment: AlignmentType.CENTER, keepNext: true,
    // LibreOffice 可能将继承的正文行距用于内嵌图片而裁切图片，显式为整图保留最小行高。
    spacing: {before: 80, after: 80, line: displayHeight * 15 + 120, lineRule: LineRuleType.AT_LEAST},
    children: [new ImageRun({type: asset.absolute_path.toLowerCase().endsWith('.png') ? 'png' : 'jpg',
      data, transformation: {width: displayWidth, height: displayHeight}})]});
}
const children = [
  new Paragraph({alignment: AlignmentType.CENTER, spacing: {before: 800, after: 480},
    children: [new TextRun({text: input.topic, bold: true, size: 36})]}),
  new Paragraph({alignment: AlignmentType.CENTER, spacing: {after: 700},
    children: [new TextRun({text: '技术论文 · 可复现参考实现与实验验证', size: 22, color: '555555'})]}),
  new Paragraph({heading: HeadingLevel.HEADING_1, text: '摘要'}), ...body(input.abstract),
  new Paragraph({children: [new TextRun({text: '关键词：', bold: true}), new TextRun(input.keywords.join('；'))], spacing: {before: 160, after: 200}}),
];
for (const item of input.outline) {
  const depth = item.section_id.split('.').length;
  children.push(new Paragraph({heading: [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][depth - 1],
    text: depth === 1 ? item.title : `${item.section_id} ${item.title}`,
    pageBreakBefore: item.section_id === '1', keepNext: true, spacing: {before: 240, after: 140}}));
  const record = records.get(item.section_id);
  if (!record) continue;
  children.push(...body(record.content));
  for (const itemAsset of record.assets) {
    const asset = assets.get(itemAsset.asset_id);
    if (asset.kind === 'table') children.push(caption(asset), table(asset), new Paragraph({spacing: {after: 100}}));
    else children.push(figure(asset), caption(asset));
  }
}
children.push(new Paragraph({heading: HeadingLevel.HEADING_1, text: '参考文献', keepNext: true, spacing: {before: 240, after: 140}}));
usedCitations.forEach((key, index) => {
  const entry = input.bib_pool.find(b => b.key === key);
  if (!entry) throw new Error(`Unknown citation ${key}`);
  children.push(new Paragraph({children: [new TextRun({text: `[${index + 1}] ${entry.formatted || `${entry.authors}. ${entry.title}. ${entry.url}`}`, size: 20})],
    spacing: {after: 160, line: 300}, widowControl: true}));
});
const doc = new Document({creator: '论文撰写系统', title: input.topic,
  styles: {default: {document: {run: {font, size: 24}, paragraph: {spacing: {line: 360}}}},
    paragraphStyles: [
      {id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
       run: {font, bold: true, size: 30}, paragraph: {outlineLevel: 0, keepNext: true}},
      {id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
       run: {font, bold: true, size: 27}, paragraph: {outlineLevel: 1, keepNext: true}},
      {id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
       run: {font, bold: true, size: 24}, paragraph: {outlineLevel: 2, keepNext: true}},
    ]},
  sections: [{properties: {page: {size: {width: PAGE_WIDTH, height: PAGE_HEIGHT},
                                 margin: {top: 1247, bottom: 1247, left: MARGIN, right: MARGIN}}},
    headers: {default: new Header({children: [new Paragraph({alignment: AlignmentType.CENTER,
      children: [new TextRun({text: '共享设备预约系统：设计与一致性验证', size: 18, color: '777777'})]})]})},
    footers: {default: new Footer({children: [new Paragraph({alignment: AlignmentType.CENTER,
      children: [new TextRun({children: ['第 ', PageNumber.CURRENT, ' 页'], size: 18})]})]})}, children}],
});
Packer.toBuffer(doc).then(buffer => fs.writeFileSync(output, buffer)).catch(err => {console.error(err); process.exit(1);});
