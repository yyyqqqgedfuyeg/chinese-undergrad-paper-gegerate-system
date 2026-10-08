"""Independent acceptance checks for 附件9; optional full PDF raster comparison.

.venv/bin/python test/verify_template_replication.py --out <real-run-dir> --render
Tests observable requirements independently of the agent-authored cleaning plan.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from zipfile import ZipFile
from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{' + NS['w'] + '}'


def run(out, render=False):
    out = Path(out).resolve()
    source = ROOT/'test/tmp/附件9 正文格式模板.docx'
    def part(path, name='word/document.xml'):
        with ZipFile(path) as z:
            return z.read(name)
    def root(path):
        return ET.fromstring(part(path))
    clean = root(out/'clean-template.docx')
    filled = root(out/'filled-demo.docx')
    ps = clean.find('w:body',NS).findall('w:p',NS)
    style_root = ET.fromstring(part(out/'clean-template.docx','word/styles.xml'))
    styles = {n.get(W+'styleId'):n for n in style_root.findall('w:style',NS)}
    def paragraph_style(p):
        node=p.find('w:pPr/w:pStyle',NS)
        return styles.get(node.get(W+'val')) if node is not None else None
    checks = []
    def check(condition, message):
        checks.append({'passed':bool(condition),'check':message})
    def text(p):
        return ''.join(p.xpath('.//w:t/text()',namespaces=NS))
    def value(run, prop, attr='val'):
        e = run.find('w:rPr/w:'+prop,NS)
        if e is not None and e.get(W+attr) is not None:return e.get(W+attr)
        p=run
        while p is not None and p.tag != W+'p':p=p.getparent()
        style=paragraph_style(p) if p is not None else None
        e=style.find('w:rPr/w:'+prop,NS) if style is not None else None
        return e.get(W+attr) if e is not None else None
    def content_run(index):
        return next(r for r in ps[index].findall('.//w:r',NS) if '{{' in text(r))
    check(len(clean.findall('.//w:sectPr',NS)) == 6,'All six source sections retained')
    check(len(clean.findall('.//w:tbl',NS)) == 1,'Source table retained')
    check(text(ps[26]) == text(root(source).find('w:body',NS).findall('w:p',NS)[26]),'Declaration preserved verbatim')
    for i,font,size in [(8,'黑体','32'), *[(i,'楷体','30') for i in (13,14,15,16,17)], (102,'宋体','18'),(106,'宋体','18')]:
        r = content_run(i)
        check(value(r,'rFonts','eastAsia') == font and value(r,'sz') == size, f'Paragraph {i}: required {font} {int(size)/2}pt')
        check(value(r,'color') in ('000000','auto',None),f'Paragraph {i}: placeholder is not red')
    for i in (74,78,81,84,88,92,94,97,113,114,121):
        spacing = ps[i].find('w:pPr/w:spacing',NS)
        inherited=paragraph_style(ps[i])
        base_spacing=inherited.find('w:pPr/w:spacing',NS) if inherited is not None else None
        attrs=dict(base_spacing.attrib) if base_spacing is not None else {}
        if spacing is not None:attrs.update(spacing.attrib)
        check(attrs.get(W+'line') == '360' and attrs.get(W+'lineRule') == 'auto',f'Paragraph {i}: actual 1.5 line spacing, not fixed points')
        r = content_run(i)
        expected_font = 'Times New Roman' if i in (81,84) else '宋体'
        attr = 'ascii' if i in (81,84) else 'eastAsia'
        check(value(r,'rFonts',attr) == expected_font and value(r,'sz') == '24', f'Paragraph {i}: required {expected_font} 12pt')
    all_text = ''.join(text(p) for p in clean.findall('.//w:p',NS))
    markers = re.findall(r'\{\{[^{}]+\}\}',all_text)
    check(bool(markers) and len(markers) == len(set(markers)), 'Clean placeholders are present and globally unique')
    check('我是表格' not in all_text,'All table sample content removed')
    check('{{' not in ''.join(filled.xpath('//w:t/text()',namespaces=NS)), 'Filled demo contains no unresolved placeholder')
    with ZipFile(out/'clean-template.docx') as z:
        header_names = [name for name in z.namelist() if re.fullmatch(r'word/header[0-9]+\.xml',name)]
    filled_title = text(filled.find('w:body',NS).findall('w:p',NS)[73])
    check(bool(header_names),'Source header retained')
    for name in header_names:
        clean_header, filled_header = ET.fromstring(part(out/'clean-template.docx',name)),ET.fromstring(part(out/'filled-demo.docx',name))
        clean_text = ''.join(clean_header.xpath('//w:t/text()',namespaces=NS))
        filled_text = ''.join(filled_header.xpath('//w:t/text()',namespaces=NS))
        check('毕业设计题目' not in clean_text and '{{' in clean_text,f'{name}: sample title cleaned to placeholder')
        check(filled_title in filled_text and '{{' not in filled_text,f'{name}: filled title agrees with main title')
    # Filling may only alter text and xml:space, preserving every style/field node.
    def structure(r):
        r = deepcopy(r)
        for n in r.findall('.//w:t',NS):
            n.text = ''
            n.attrib.pop('{http://www.w3.org/XML/1998/namespace}space',None)
        return ET.tostring(r,method='c14n')
    check(structure(clean) == structure(filled),'Filling preserves all run/paragraph formatting and document structure')
    for name in header_names:
        check(structure(ET.fromstring(part(out/'clean-template.docx',name))) == structure(ET.fromstring(part(out/'filled-demo.docx',name))), f'{name}: header formatting preserved while filling')
    for name in ('word/styles.xml','word/fontTable.xml','word/theme/theme1.xml'):
        check(part(out/'clean-template.docx',name) == part(out/'filled-demo.docx',name), f'Filling preserves {name}')
    plan=json.loads((out/'cleaning-plan.json').read_text())
    if plan.get('style_rebuild'):
        original_styles=ET.fromstring(part(source,'word/styles.xml'))
        old_ids={n.get(W+'styleId') for n in original_styles.findall('w:style',NS)}
        check(not (old_ids & set(styles)), 'Every source/default style definition has been removed')
        check(all(n.get(W+'customStyle')=='1' for n in styles.values()), 'Every saved style is newly defined as custom')
        check(not style_root.findall('w:latentStyles/w:lsdException',NS), 'Source builtin latent style entries have been cleared')
        required={'论文正文','论文一级标题','论文二级标题','论文三级标题','论文中文摘要','论文英文摘要','论文图题','论文表题','论文页眉','论文页脚'}
        actual_names={n.find('w:name',NS).get(W+'val') for n in styles.values()}
        check(required <= actual_names,'Required Chinese named styles are present')
        check(all(n.find('w:qFormat',NS) is not None and n.find('w:hidden',NS) is None and n.find('w:semiHidden',NS) is None for n in styles.values()), 'All new styles carry visible gallery metadata')
        check(all(ps[i].find('w:pPr/w:pStyle',NS).get(W+'val')==sid for i,sid in ((88,'PaperBody'),(91,'PaperHeading1'),(93,'PaperHeading2'),(96,'PaperHeading3'))), 'Body and three heading levels actually use the new styles')
        r=content_run(88)
        check(r.find('w:rPr/w:sz',NS) is None and r.find('w:rPr/w:rFonts',NS) is None, 'Body text inherits its font and size from the named style')
        for sid,level in (('PaperHeading1','0'),('PaperHeading2','1'),('PaperHeading3','2'),('PaperBody','9')):
            check(styles[sid].find('w:pPr/w:outlineLvl',NS).get(W+'val')==level,f'{sid}: correct outline level {level}')
        refs=[]
        with ZipFile(out/'clean-template.docx') as z:
            for name in z.namelist():
                if not name.endswith('.xml'):continue
                tree=ET.fromstring(z.read(name))
                refs.extend(n.get(W+'val') for n in tree.xpath('//w:pStyle|//w:rStyle|//w:tblStyle|//w:basedOn|//w:next|//w:link|//w:styleLink|//w:numStyleLink',namespaces=NS))
        check(set(refs)<=set(styles), 'No dangling style reference remains in any XML part')
    xsd = {}
    for filename in ('replica.docx','clean-template.docx','filled-demo.docx'):
        args = [str(ROOT/'.venv/bin/python'),str(ROOT/'skills/docx/scripts/office/validate.py'),str(out/filename)]
        result = subprocess.run(args,capture_output=True,text=True)
        (out/(filename+'.xsd.txt')).write_text(result.stdout+result.stderr)
        xsd[filename] = {'returncode':result.returncode,'log':filename+'.xsd.txt'}
        if filename != 'replica.docx':
            check(result.returncode == 0,f'{filename}: full XSD/schema validation')
    rendering = None
    layout = None
    if render:
        rendering = render_documents(source,out)
        check(rendering['replica_pixels_identical'], 'Source and replica have identical raster pages')
        check(rendering['source_page_count'] == rendering['replica_page_count'], 'Source and replica have identical page counts')
        layout = {}
        for kind in ('clean','filled'):
            check(rendering[kind+'_page_count'] > 0,f'{kind} document renders to nonempty PDF')
            pdf = next((out/'render'/kind).glob('*.pdf'))
            bbox = subprocess.run(['pdftotext','-bbox-layout',str(pdf),'-'],check=True,capture_output=True).stdout
            pages = ET.fromstring(bbox,ET.XMLParser(resolve_entities=False,no_network=True)).findall('.//{http://www.w3.org/1999/xhtml}page')
            overflow = []
            for i,page in enumerate(pages,1):
                for word in page.findall('.//{http://www.w3.org/1999/xhtml}word'):
                    if float(word.get('xMax')) > float(page.get('width'))-20 or float(word.get('xMin')) < 20 or float(word.get('yMin')) < 20 or float(word.get('yMax')) > float(page.get('height'))-20:
                        overflow.append({'page':i,'text':word.text,'bbox':dict(word.attrib)})
            layout[kind] = {'overflow':overflow}
            check(not overflow,f'{kind}: no PDF text crosses the page safety boundary')
        pdf = next((out/'render'/'filled').glob('*.pdf'))
        extracted = subprocess.run(['pdftotext','-layout',str(pdf),'-'],check=True,capture_output=True,text=True).stdout
        values = json.loads((out/'values.json').read_text())
        normalize = lambda s:re.sub(r'\s+','',s)
        for key in ('{{英文摘要}}','{{英文关键词}}'):
            check(normalize(values[key]) in normalize(extracted),f'Filled PDF contains the complete {key} text without clipping')
    report = {'passed':all(c['passed'] for c in checks),'checks':checks,'xsd':xsd,'rendering':rendering,'layout':layout}
    (out/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'check_count':len(checks),'failed_checks':[c['check'] for c in checks if not c['passed']],'rendering':{k:v for k,v in (rendering or {}).items() if k.endswith('page_count') or k=='replica_pixels_identical'},'report':str(out/'acceptance.json')},ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


def render_documents(source,out):
    render = out/'render'
    render.mkdir(exist_ok=True)
    hashes = {}
    counts = {}
    for kind,path in [('source',source),('replica',out/'replica.docx'),('clean',out/'clean-template.docx'),('filled',out/'filled-demo.docx')]:
        dest = render/kind
        dest.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='docx-lo-') as profile:
            command = ['libreoffice','-env:UserInstallation='+Path(profile).as_uri(),'--headless','--convert-to','pdf','--outdir',str(dest),str(path)]
            proc = subprocess.run(command,capture_output=True,text=True,timeout=120)
        (dest/'conversion.txt').write_text(proc.stdout+proc.stderr)
        pdf = dest/(path.stem+'.pdf')
        if proc.returncode != 0 or not pdf.exists():
            raise RuntimeError(f'Rendering failed: {kind}: {proc.stdout} {proc.stderr}')
        subprocess.run(['pdftoppm','-r','72','-png',str(pdf),str(dest/'page')],check=True,capture_output=True,timeout=120)
        pages = sorted(dest.glob('page-*.png'))
        hashes[kind] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in pages]
        counts[kind] = len(pages)
    return {**{k+'_page_count':v for k,v in counts.items()},'replica_pixels_identical':hashes['source'] == hashes['replica'],'page_png_sha256':hashes,'scope':'LibreOffice in this environment; installed font substitutions apply equally to both source and replica.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    parser.add_argument('--render',action='store_true')
    args = parser.parse_args()
    run(args.out,args.render)
