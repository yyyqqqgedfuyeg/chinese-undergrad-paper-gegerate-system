#!/usr/bin/env python3
"""Lossless DOCX template extraction, explicit cleaning, filling and validation.

Cleaning edits affect document/header/footer XML. Optional style_rebuild
replaces all source styles with visible named styles and remaps references.
Themes, fonts, media and relationships are preserved. A plan is a reviewable list of substring replacements
and narrowly scoped formatting corrections with evidence from the source.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from zipfile import ZipFile

from lxml import etree as ET

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
STORY_PATTERN = re.compile(r'word/(document|header[0-9]+|footer[0-9]+)\.xml$')
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
PARSER = ET.XMLParser(resolve_entities=False, no_network=True)


def q(name):
    return f'{{{W}}}{name}'


def parse(data):
    return ET.fromstring(data, PARSER)


def xml(element):
    return ET.tostring(element, encoding='unicode') if element is not None else None


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def package(path):
    with ZipFile(path) as z:
        if z.testzip():
            raise ValueError('Corrupt ZIP')
        return {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}


def paragraphs(root):
    return root.find('w:body', NS).findall('w:p', NS)


def text(p):
    return ''.join(n.text or '' for n in p.findall('.//w:t',NS))


def props(element):
    """Raw properties, retaining namespaces/attributes in the companion XML."""
    result = {}
    if element is not None:
        for child in element:
            result[ET.QName(child).localname] = {
                ET.QName(k).localname: v for k, v in child.attrib.items()
            }
    return result


def merged(*items):
    out = {}
    for item in items:
        for key, attrs in item.items():
            out.setdefault(key, {}).update(attrs)
    return out


def inspect(source, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    parts = package(source)
    root = parse(parts['word/document.xml'])
    styles = parse(parts['word/styles.xml'])
    by_id = {s.get(q('styleId')): s for s in styles.findall('w:style', NS)}
    default = next((k for k,s in by_id.items() if s.get(q('type')) == 'paragraph' and s.get(q('default')) == '1'), None)

    def chain(style_id, seen=None):
        seen = set() if seen is None else seen
        if style_id not in by_id or style_id in seen:
            return []
        seen.add(style_id)
        s = by_id[style_id]
        base = s.find('w:basedOn', NS)
        return (chain(base.get(q('val')), seen) if base is not None else []) + [s]

    records = []
    for i, p in enumerate(paragraphs(root)):
        ppr = p.find('w:pPr', NS)
        ps = p.find('w:pPr/w:pStyle', NS)
        sid = ps.get(q('val')) if ps is not None else default
        ancestry = chain(sid)
        paragraph_props = merged(props(styles.find('w:docDefaults/w:pPrDefault/w:pPr', NS)), *(props(s.find('w:pPr', NS)) for s in ancestry), props(ppr))
        runs = []
        for j, r in enumerate(p.findall('.//w:r', NS)):
            rs = r.find('w:rPr/w:rStyle', NS)
            rchain = chain(rs.get(q('val'))) if rs is not None else []
            # Preserve raw data as authoritative. Toggle properties and theme font
            # references require a renderer; do not pretend this is a full cascade.
            runs.append({'index': j, 'text': text(r), 'direct': props(r.find('w:rPr', NS)), 'rPr_xml': xml(r.find('w:rPr', NS)), 'style_chain': [s.get(q('styleId')) for s in ancestry + rchain]})
        records.append({'index': i, 'text': text(p), 'style_id': sid, 'inherited_run_properties':merged(props(styles.find('w:docDefaults/w:rPrDefault/w:rPr',NS)), *(props(s.find('w:rPr',NS)) for s in ancestry)), 'pPr_xml': xml(ppr), 'paragraph_properties': paragraph_props, 'runs': runs})
    assets = out / 'format'
    assets.mkdir(exist_ok=True)
    for name, data in parts.items():
        if name in ('word/styles.xml', 'word/fontTable.xml', 'word/settings.xml') or name.startswith('word/theme/'):
            dest = assets / name.removeprefix('word/')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    fonts = sorted(set(parse(parts['word/fontTable.xml']).xpath('//w:font/@w:name', namespaces=NS)))
    installed = {}
    for font in fonts:
        if shutil.which('fc-match') is None:
            installed[font] = {'matched_family':None, 'exact_family_available':None, 'reason':'fontconfig is unavailable'}
            continue
        match = subprocess.run(['fc-match', '-f', '%{family}', font], capture_output=True, text=True, check=True).stdout
        installed[font] = {'matched_family': match, 'exact_family_available': font.casefold() in [s.strip().casefold() for s in match.split(',')]}
    inventory = {
        'schema_version': 1, 'source': str(Path(source).resolve()),
        'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        'part_sha256': {k: hashlib.sha256(v).hexdigest() for k,v in parts.items()},
        'sections_xml': [xml(s) for s in root.findall('.//w:sectPr', NS)],
        'tables_xml': [xml(t) for t in root.findall('.//w:tbl', NS)],
        'styles': {k: {'name': s.find('w:name',NS).get(q('val')) if s.find('w:name',NS) is not None else k, 'xml': xml(s)} for k,s in by_id.items()},
        'fonts': installed, 'embedded_font_parts': [k for k in parts if k.startswith('word/fonts/')],
        'paragraphs': records,
        'stories': {name:[{'index':i,'text':text(p),'pPr_xml':xml(p.find('w:pPr',NS)),'runs':[{'text':text(r),'direct':props(r.find('w:rPr',NS))} for r in p.findall('.//w:r',NS)]} for i,p in enumerate(parse(data).findall('.//w:p',NS))] for name,data in parts.items() if STORY_PATTERN.fullmatch(name) and name != 'word/document.xml'},
        'table_paragraphs': [{'index':i,'text':text(p)} for i,p in enumerate(root.findall('.//w:tbl//w:p',NS))],
        'limitations': ['Run properties are raw, not a complete Word formatting cascade; exact styles, themes and defaults are stored in format/.', 'Font names and style definitions are stored; proprietary font binaries are not supplied.'],
    }
    save(out / 'inventory.json', inventory)
    # Small agent-facing view avoids large XML payloads/context truncation.
    summary = {k: inventory[k] for k in ('source_sha256','fonts','limitations')} | {
        'stories':inventory['stories'],
        'table_paragraphs':inventory['table_paragraphs'],
        'section_count':len(inventory['sections_xml']), 'table_count':len(inventory['tables_xml']),
        'paragraphs': [{k:p[k] for k in ('index','text','style_id','paragraph_properties','inherited_run_properties')} | {
            'runs': [{'text':r['text'],'direct':r['direct']} for r in p['runs'] if r['text']]
        } for p in records if p['text'].strip()],
    }
    # One paragraph per line: compact enough for an agent to read in one call.
    header = {k:v for k,v in summary.items() if k != 'paragraphs'}
    with (out/'summary.json').open('w',encoding='utf-8') as f:
        f.write(json.dumps(header,ensure_ascii=False)[:-1] + ', "paragraphs": [\n')
        f.write(',\n'.join(json.dumps(p,ensure_ascii=False) for p in summary['paragraphs']))
        f.write('\n]}\n')
    print(json.dumps({'inventory':str(out/'inventory.json'), 'summary':str(out/'summary.json'), 'sections':len(inventory['sections_xml']), 'fonts':installed}, ensure_ascii=False))
    return inventory


def replace_span(p, old, new):
    """Replace a unique span even across fragmented runs, preserving unaffected text."""
    nodes = p.findall('.//w:t', NS)
    full = ''.join(n.text or '' for n in nodes)
    if not old or full.count(old) != 1:
        raise ValueError(f'Replacement must match exactly once: {old!r}')
    start = full.index(old)
    end = start + len(old)
    pos = 0
    inserted = False
    affected = []
    for n in nodes:
        value = n.text or ''
        stop = pos + len(value)
        if pos < end and stop > start:
            a, b = max(start-pos, 0), min(end-pos, len(value))
            n.text = value[:a] + (new if not inserted else '') + value[b:]
            n.set(XML_SPACE, 'preserve')
            if not inserted:
                affected.append(n.getparent())
            inserted = True
        pos = stop
    return affected


def set_props(parent, tag, values):
    from docx.oxml import OxmlElement
    # python-docx's ordered inserters preserve schema order for new properties.
    if tag == 'pPr':
        pr = parent.get_or_add_pPr()
    else:
        pr = parent.get_or_add_rPr()
    for name, attrs in values.items():
        if not re.fullmatch('[A-Za-z][A-Za-z0-9]*', name):
            raise ValueError(f'Invalid property: {name}')
        old = pr.find(q(name))
        if old is not None:
            pr.remove(old)
        getter = getattr(pr, f'get_or_add_{name}', None)
        if getter is not None:
            child = getter()
        else:
            child = OxmlElement('w:' + name)
            sequences = {
                'pPr': 'pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange'.split(),
                'rPr': 'rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange'.split(),
            }
            sequence = sequences[tag]
            if name not in sequence:
                raise ValueError(f'Unsupported {tag} property: {name}')
            successors = {q(s) for s in sequence[sequence.index(name)+1:]}
            index = next((i for i,c in enumerate(pr) if c.tag in successors), len(pr))
            pr.insert(index,child)
        for key, value in attrs.items():
            child.set(q(key), str(value))


def apply_plan(parts, plan):
    # Register python-docx's CT_P / CT_R classes for ordered property insertion.
    from docx.oxml import parse_xml
    roots = {'word/document.xml':parse_xml(parts['word/document.xml'])}
    touched = set()
    used = set()
    for edit in plan['edits']:
        idx = edit['paragraph']
        name = edit.get('part','word/document.xml')
        if not STORY_PATTERN.fullmatch(name) or name not in parts:
            raise ValueError(f'Invalid story part: {name}')
        if name not in roots:
            roots[name] = parse_xml(parts[name])
        root = roots[name]
        ps = paragraphs(root) if name == 'word/document.xml' else root.findall('.//w:p',NS)
        touched.add(name)
        scope = edit.get('scope','body')
        if scope not in ('body','table'):
            raise ValueError(f'Invalid scope: {scope}')
        key = (name,scope,idx)
        if key in used:
            raise ValueError(f'Duplicate paragraph edit: {idx}')
        used.add(key)
        p = (ps if scope == 'body' else root.findall('.//w:tbl//w:p',NS))[idx]
        if text(p) != edit['expected_text']:
            raise ValueError(f'Stale plan at paragraph {idx}')
        if not edit.get('evidence'):
            raise ValueError('Each edit requires evidence')
        for replacement in edit.get('replacements', []):
            runs = replace_span(p, replacement['old'], replacement['new'])
            for r in runs:
                if replacement.get('run_properties'):
                    set_props(r, 'rPr', replacement['run_properties'])
        if edit.get('paragraph_properties'):
            set_props(p, 'pPr', edit['paragraph_properties'])
    data = dict(parts)
    for name in touched:
        data[name] = ET.tostring(roots[name], xml_declaration=True, encoding='UTF-8', standalone=True)
    return data


def write_package(path, parts):
    from zipfile import ZIP_DEFLATED
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def normalize_style_order(data):
    """Repair source style child order without changing style values or content."""
    root = parse(data)
    names = ('name aliases basedOn next link autoRedefine hidden uiPriority semiHidden '
             'unhideWhenUsed qFormat locked personal personalCompose personalReply rsid '
             'pPr rPr tblPr trPr tcPr tblStylePr').split()
    order = {q(name):i for i,name in enumerate(names)}
    changed = []
    for style in root.findall('w:style',NS):
        children = list(style)
        sorted_children = sorted(children,key=lambda c:order.get(c.tag,len(order)))
        if children != sorted_children:
            style[:] = sorted_children
            changed.append(style.get(q('styleId')))
    return (ET.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True) if changed else data), changed


def transform(parts, plan):
    clean = apply_plan(parts, plan)
    if plan.get('style_rebuild'):
        import importlib.util
        path = Path(__file__).with_name('rebuild_styles.py')
        spec = importlib.util.spec_from_file_location('docx_rebuild_styles',path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        clean, report = module.rebuild(clean,plan['style_rebuild'])
        return clean, [], report
    clean['word/styles.xml'], repairs = normalize_style_order(clean['word/styles.xml'])
    return clean, repairs, None


def build(source, out, plan_path):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    plan = load(plan_path)
    expected = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    if plan['source_sha256'] != expected:
        raise ValueError('Plan source hash mismatch')
    parts = package(source)
    clean, repaired_styles, style_report = transform(parts,plan)
    if style_report:
        save(out/'style-catalog.json',style_report)
    save(out/'style-order-repairs.json', {'style_ids':repaired_styles,'reason':'CT_Style child ordering only; all property values are preserved.'})
    write_package(out/'replica.docx', parts)
    write_package(out/'clean-template.docx', clean)
    shutil.copyfile(plan_path, out/'cleaning-plan.json') if Path(plan_path).resolve() != (out/'cleaning-plan.json').resolve() else None
    inspect(out/'clean-template.docx', out/'clean-format')
    print(json.dumps({'replica':str(out/'replica.docx'),'clean_template':str(out/'clean-template.docx')}, ensure_ascii=False))


def fill(template, values_path, output):
    parts = package(template)
    values = load(values_path)
    found = set()
    for name in list(parts):
        if not STORY_PATTERN.fullmatch(name):
            continue
        root = parse(parts[name])
        changed = False
        for p in root.findall('.//w:p', NS):
            for marker in re.findall(r'\{\{[^{}]+\}\}', text(p)):
                if marker not in values:
                    raise ValueError(f'Missing value for {marker}')
                value = values[marker]
                if not isinstance(value,str) or any(c in value for c in '\r\n') or '{{' in value:
                    raise ValueError('Values must be single-paragraph strings without placeholders')
                replace_span(p, marker, value)
                found.add(marker)
                changed = True
        if changed:
            parts[name] = ET.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    if set(values) != found:
        raise ValueError(f'Unused values: {set(values)-found}')
    write_package(output, parts)
    print(str(output))


def canonical(root):
    return ET.tostring(root, method='c14n')


def verify(source, out, plan_path):
    out = Path(out)
    original = package(source)
    replica = package(out/'replica.docx')
    clean = package(out/'clean-template.docx')
    plan = load(plan_path)
    errors = []
    def check(condition, description):
        if not condition:
            errors.append(description)
    check(plan.get('source_sha256') == hashlib.sha256(Path(source).read_bytes()).hexdigest(), 'Cleaning plan source hash mismatch')
    check(replica == original, 'Replica ZIP parts differ from source')
    check(set(clean) == set(original), 'Package parts lost or added')
    expected, repaired_styles, style_report = transform(original,plan)
    for name in original:
        check(clean.get(name) == expected[name], f'Unexpected change to {name}')
    before = parse(original['word/document.xml'])
    after = parse(clean['word/document.xml'])
    for expr in ('.//w:sectPr', './/w:drawing', './/w:pict', './/w:instrText', './/w:fldChar', './/w:bookmarkStart', './/w:bookmarkEnd', './/w:r/w:tab', './/w:br'):
        check([canonical(x) for x in before.findall(expr, NS)] == [canonical(x) for x in after.findall(expr,NS)], f'Protected structure changed: {expr}')
    # Table text can be cleaned; geometry, borders and other properties cannot.
    def table_structure(r):
        r = deepcopy(r)
        if style_report:
            for tbl in r.findall('.//w:tbl',NS):
                for n in tbl.findall('.//w:pPr',NS)+tbl.findall('.//w:rPr',NS)+tbl.findall('w:tblPr/w:tblStyle',NS):
                    n.getparent().remove(n)
        for n in r.findall('.//w:tbl//w:t',NS):
            n.text = ''
            n.attrib.pop(XML_SPACE,None)
        return [canonical(t) for t in r.findall('.//w:tbl',NS)]
    check(table_structure(before) == table_structure(after), 'Table structure changed')
    check(len(paragraphs(before)) == len(paragraphs(after)), 'Paragraph count changed')
    leftovers = []
    for name,data in clean.items():
        if not STORY_PATTERN.fullmatch(name):
            continue
        for i,p in enumerate(parse(data).findall('.//w:p',NS)):
            t = text(p)
            if re.search(r'\*{3,}|×{3,}|格式参照此处|倍行间距|号字|小三号|注解示例|不少于15篇|重点、典型编码|我是表格|毕业设计题目', t):
                leftovers.append({'part':name, 'paragraph':i,'text':t})
    check(not leftovers, f'Unclean instructional text: {leftovers}')
    style_checks = verify_named_styles(clean,plan,errors) if style_report else None
    from docx import Document
    Document(str(out/'clean-template.docx'))
    report = {'passed':not errors, 'errors':errors, 'replica_parts_identical':replica == original, 'section_count':len(after.findall('.//w:sectPr', NS)), 'paragraph_count':len(paragraphs(after)), 'edit_count':len(plan['edits']), 'style_order_repairs':repaired_styles, 'named_styles':style_checks, 'leftovers':leftovers, 'scope':'ZIP/XML fidelity and cleaning-plan conformance; rendering/font availability are separate checks.'}
    save(out/'verification.json', report)
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(1)
    return report


def verify_named_styles(parts,plan,errors):
    styles=parse(parts['word/styles.xml'])
    definitions={s.get(q('styleId')):s for s in styles.findall('w:style',NS)}
    config=plan['style_rebuild']
    expected={s['id'] for s in config['styles']}
    counts={sid:0 for sid in expected}
    for sid in expected:
        s=definitions.get(sid)
        if s is None:
            errors.append(f'Missing named style: {sid}');continue
        if s.find('w:qFormat',NS) is None or s.find('w:semiHidden',NS) is not None or s.find('w:hidden',NS) is not None:
            errors.append(f'Named style is not visible in gallery: {sid}')
        if s.get(q('customStyle'))!='1':errors.append(f'Named style is not custom: {sid}')
    dangling=[]
    for name,data in parts.items():
        if not name.endswith('.xml'):continue
        root=parse(data)
        for node in root.xpath('//w:pStyle|//w:rStyle|//w:tblStyle|//w:basedOn|//w:next|//w:link|//w:styleLink|//w:numStyleLink',namespaces=NS):
            sid=node.get(q('val'))
            if sid not in definitions:dangling.append({'part':name,'style':sid})
        if STORY_PATTERN.fullmatch(name):
            for p in root.findall('.//w:p',NS):
                node=p.find('w:pPr/w:pStyle',NS)
                sid=node.get(q('val')) if node is not None else None
                if sid not in expected:errors.append(f'Paragraph without a new named style in {name}')
                else:counts[sid]+=1
    if dangling:errors.append(f'Dangling style references: {dangling}')
    if any(n==0 for n in counts.values()):errors.append('New style not applied to any paragraph')
    return {'paragraph_style_count':len(expected),'total_style_count':len(definitions),'applied_counts':counts,'dangling_references':dangling,'gallery_visible':not any('gallery' in e for e in errors)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest='action',required=True)
    for action in ('inspect','build','verify'):
        sub = s.add_parser(action)
        sub.add_argument('--source',required=True)
        sub.add_argument('--out',required=True)
        if action != 'inspect':
            sub.add_argument('--plan',required=True)
    sub = s.add_parser('fill')
    sub.add_argument('--template',required=True)
    sub.add_argument('--values',required=True)
    sub.add_argument('--output',required=True)
    a = p.parse_args()
    if a.action == 'fill':
        fill(a.template,a.values,a.output)
    elif a.action == 'inspect':
        inspect(a.source,a.out)
    elif a.action == 'build':
        build(a.source,a.out,a.plan)
    else:
        verify(a.source,a.out,a.plan)

if __name__ == '__main__':
    main()
